# Export layout and byte-identical output for the same seed
from __future__ import annotations

import json
from pathlib import Path

import pytest
from orggraph_dataset.config import OrgGraphConfig
from orggraph_dataset.constants import MANIFEST_FILE, METADATA_DIR
from orggraph_dataset.pipeline.exporter import OutputDirectoryError, prepare_output_dir
from orggraph_dataset.pipeline.loader import DatasetReader
from orggraph_dataset.pipeline.orchestrator import GenerationResult, GenerationSettings, run_generation
from orggraph_dataset.schemas import EmployeeObservation, ReportingEdge
from orggraph_dataset.utils.jsonl import JsonlWriter, dumps, iter_jsonl, read_json
from orggraph_dataset.validation import validate_dataset_dir


def _generate(config: OrgGraphConfig, out: Path, **kwargs: object) -> GenerationResult:
    settings = GenerationSettings.from_config(
        config, companies=6, target_employees=600, output_dir=out, validate_after_export=False, **kwargs
    )
    return run_generation(config, settings)


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    with JsonlWriter(path, buffer_lines=2) as writer:
        writer.write_many({"b": i, "a": "é"} for i in range(5))
    rows = list(iter_jsonl(path))
    assert rows == [{"a": "é", "b": i} for i in range(5)]
    assert dumps({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_export_layout_and_reload(small_dataset: GenerationResult) -> None:
    root = small_dataset.output_dir
    reader = DatasetReader(root)
    assert reader.splits() == ["train", "validation", "test", "challenge"]
    for split in reader.splits():
        assert (root / "observed" / split / "observations.jsonl").exists()
        assert (root / "ground_truth" / split / "reporting_edges.jsonl").exists()
    edges = [
        ReportingEdge.model_validate(r)
        for s in reader.splits()
        for r in reader.iter_ground_truth(s, "reporting_edges")
    ]
    assert len(edges) == small_dataset.manifest.employee_count
    obs = [EmployeeObservation.model_validate(r) for r in reader.iter_observed("train", "observations")]
    assert obs and all(o.observation_id.startswith("obs_") for o in obs)
    chunks = list(reader.iter_company_chunks("train"))
    assert len(chunks) == small_dataset.manifest.split_distribution["train"]["companies"]


def test_observed_files_contain_no_manager_ids(small_dataset: GenerationResult) -> None:
    for path in (small_dataset.output_dir / "observed").rglob("*.jsonl"):
        text = path.read_text(encoding="utf-8")
        for forbidden in (
            "manager_employee_id",
            "canonical_title",
            "position_id",
            "hierarchy_depth",
            "noise_applied",
        ):
            assert forbidden not in text, (path, forbidden)


def test_manifest_contents(small_dataset: GenerationResult) -> None:
    manifest = read_json(small_dataset.output_dir / METADATA_DIR / MANIFEST_FILE)
    assert manifest["random_seed"] == 11
    assert manifest["company_count"] == 16
    assert manifest["reporting_edge_count"] + manifest["root_count"] == manifest["employee_count"]
    assert set(manifest["noise_profile"]["profiles"]) == {"medium_noise", "enterprise_complexity"}
    assert len(manifest["output_file_checksums"]) == 4 * 11
    assert sum(manifest["industry_distribution"].values()) == 16


def test_validator_detects_tampering(
    small_dataset: GenerationResult, config: OrgGraphConfig, tmp_path: Path
) -> None:
    import shutil

    copy_dir = tmp_path / "tampered"
    shutil.copytree(small_dataset.output_dir, copy_dir)
    path = copy_dir / "observed" / "train" / "employees.jsonl"
    rows = list(iter_jsonl(path))
    rows[0]["manager_employee_id"] = "emp_x"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    report = validate_dataset_dir(copy_dir, config)
    assert report.issue_counts["leakage.forbidden_field"] >= 1
    assert report.issue_counts["manifest.checksum_mismatch"] == 1
    assert not report.ok


def test_refuses_to_overwrite_without_flag(tmp_path: Path) -> None:
    (tmp_path / "observed").mkdir()
    with pytest.raises(OutputDirectoryError):
        prepare_output_dir(tmp_path, overwrite=False)
    prepare_output_dir(tmp_path, overwrite=True)
    assert not (tmp_path / "observed").exists()


def test_same_seed_is_reproducible(config: OrgGraphConfig, tmp_path: Path) -> None:
    a = _generate(config, tmp_path / "a", seed=5)
    b = _generate(config, tmp_path / "b", seed=5, batch_size=1)
    assert a.manifest.output_file_checksums == b.manifest.output_file_checksums
    c = _generate(config, tmp_path / "c", seed=6)
    assert a.manifest.output_file_checksums != c.manifest.output_file_checksums
