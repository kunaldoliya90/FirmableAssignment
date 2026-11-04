# Inference behaviour and graph constraints on generated datasets
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from orggraph_dataset.constants import SENIORITY_RANK
from orggraph_dataset.validation.hierarchy_validation import find_cycles
from orggraph_inference.candidates import CandidateGenerator
from orggraph_inference.data import ObservedDatasetReader
from orggraph_inference.evaluation import evaluate_predictions
from orggraph_inference.features.profiles import EmployeeProfile
from orggraph_inference.pipeline import InferenceEngine, run_dataset


def _ground_truth(dataset: Path, name: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for split_dir in sorted((dataset / "ground_truth").iterdir()):
        path = split_dir / name
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def test_profiles_recover_seniority(clean_dataset: Path, engine: InferenceEngine) -> None:
    reader = ObservedDatasetReader(clean_dataset)
    truth = {
        r["employee_id"]: r["seniority_level"] for r in _ground_truth(clean_dataset, "canonical_roles.jsonl")
    }
    agree = total = 0
    for split in reader.splits():
        for data in reader.iter_companies(split):
            for eid, profile in engine.profiles.build(data).items():
                if eid in truth:
                    total += 1
                    agree += profile.seniority == truth[eid]
    assert total > 1000
    assert agree / total > 0.97


def test_graph_constraints(noisy_dataset: Path, engine: InferenceEngine) -> None:
    reader = ObservedDatasetReader(noisy_dataset)
    for split in reader.splits():
        for data in reader.iter_companies(split):
            result = engine.infer_company(data)
            ids = {e.employee_id for e in data.employees}
            assert {p.employee_id for p in result.predictions} == ids
            parent: dict[str, str | None] = {}
            for p in result.predictions:
                assert p.company_id == data.company.company_id
                assert 0.0 <= p.confidence <= 1.0
                if p.predicted_manager_id is not None:
                    assert p.predicted_manager_id != p.employee_id
                    assert p.predicted_manager_id in ids
                    assert not result.profiles[p.predicted_manager_id].departed
                    assert result.profiles[p.predicted_manager_id].rank > result.profiles[p.employee_id].rank
                parent[p.employee_id] = p.predicted_manager_id
            assert not find_cycles(parent)
            if result.graph.root_id:
                assert parent[result.graph.root_id] is None
            assert sum(v is None for v in parent.values()) >= 1


def test_departed_employees_are_not_assigned(noisy_dataset: Path) -> None:
    departed = {r["employee_id"] for r in _ground_truth(noisy_dataset, "departed_employees.jsonl")}
    assert departed
    out = noisy_dataset.parent / "departed_check.jsonl"
    run_dataset(noisy_dataset, out)
    predictions = {json.loads(line)["employee_id"]: json.loads(line) for line in out.read_text().splitlines()}
    assigned = [d for d in departed if predictions[d]["predicted_manager_id"] is not None]
    assert len(assigned) / len(departed) < 0.1


def test_accuracy_on_clean_and_noisy(clean_dataset: Path, noisy_dataset: Path, tmp_path: Path) -> None:
    scores = {}
    for name, dataset in (("clean", clean_dataset), ("noisy", noisy_dataset)):
        out = tmp_path / f"{name}.jsonl"
        summary = run_dataset(dataset, out)
        assert summary["employees"] >= 1600
        report = evaluate_predictions(dataset, out)
        scores[name] = report["overall"]
    assert scores["clean"]["edge_precision"] > 0.9
    assert scores["noisy"]["edge_precision"] > 0.75
    for overall in scores.values():
        assert overall["coverage"] > 0.2
        assert overall["penalized_score"] > 0


def test_predictions_carry_evidence(noisy_dataset: Path, engine: InferenceEngine) -> None:
    reader = ObservedDatasetReader(noisy_dataset)
    data = next(reader.iter_companies(reader.splits()[0]))
    result = engine.infer_company(data)
    types = Counter(e["type"] for p in result.predictions for e in p.evidence)
    assert types["profile"] == len(result.predictions)
    assert types["decision"] == len(result.predictions)
    assert types["candidates"] > 0
    answered = [p for p in result.predictions if p.predicted_manager_id]
    assert answered and all(any(e["type"] == "signals" for e in p.evidence) for p in answered)


def test_evaluation_requires_finished_file(noisy_dataset: Path, tmp_path: Path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError, match="inference finished"):
        evaluate_predictions(noisy_dataset, tmp_path / "missing.jsonl")


def test_inference_is_deterministic(noisy_dataset: Path, tmp_path: Path) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    run_dataset(noisy_dataset, a)
    run_dataset(noisy_dataset, b, engine=InferenceEngine())
    assert a.read_bytes() == b.read_bytes()


def test_inference_does_not_depend_on_hash_seed(noisy_dataset: Path, tmp_path: Path) -> None:
    script = (
        "import sys; from pathlib import Path; from orggraph_inference.pipeline import run_dataset; "
        "run_dataset(Path(sys.argv[1]), Path(sys.argv[2]))"
    )
    outputs = []
    for seed in ("1", "2"):
        out = tmp_path / f"seed{seed}.jsonl"
        env = {**os.environ, "PYTHONHASHSEED": seed}
        subprocess.run([sys.executable, "-c", script, str(noisy_dataset), str(out)], check=True, env=env)
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]


def _profile(eid: str, seniority: str) -> EmployeeProfile:
    return EmployeeProfile(
        employee_id=eid,
        company_id="c",
        full_name=eid,
        employment_type="full_time",
        observation_count=1,
        sources=["hr_export"],
        seniority=seniority,
        rank=float(SENIORITY_RANK[seniority]),
        department_key="backend_engineering",
        department_top_key="engineering",
    )


def test_candidate_cap_keeps_managers_over_senior_ics() -> None:
    employee = _profile("e_zz_ic", "ic")
    senior_ics = [_profile(f"e_{i:02d}_senior", "senior_ic") for i in range(40)]
    managers = [_profile(f"e_zz_mgr_{i}", "manager") for i in range(3)]
    profiles = {p.employee_id: p for p in [employee, *senior_ics, *managers]}
    pool = CandidateGenerator(max_candidates=25).generate(profiles, None)[employee.employee_id]
    assert len(pool) == 25
    assert {m.employee_id for m in managers} <= {c.employee_id for c in pool}
