# Ground-truth isolation: the engine must only ever read observed data
from __future__ import annotations

import builtins
import io
import shutil
from pathlib import Path
from typing import Any

import orggraph_inference
import pytest
from orggraph_inference.data import ObservedDataError, ObservedDatasetReader
from orggraph_inference.pipeline import InferenceEngine, run_dataset

PACKAGE = Path(orggraph_inference.__file__).parent
GROUND_TRUTH_MARKERS = (
    "ground_truth",
    "GROUND_TRUTH",
    "reporting_edges",
    "canonical_roles",
    "observation_labels",
    "departed_employees",
    "iter_ground_truth",
    "manager_employee_id",
)


def test_engine_sources_never_reference_ground_truth() -> None:
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).as_posix()
        if relative.startswith("evaluation/") or relative == "cli.py":
            continue
        text = path.read_text(encoding="utf-8")
        allowed = {"ground_truth"} if relative == "data.py" else set()
        offenders += [(relative, m) for m in GROUND_TRUTH_MARKERS if m in text and m not in allowed]
    assert not offenders, offenders


def test_reader_refuses_ground_truth_paths(noisy_dataset: Path) -> None:
    with pytest.raises(ObservedDataError):
        ObservedDatasetReader(noisy_dataset / "ground_truth")


def test_inference_never_opens_ground_truth(
    noisy_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = builtins.open
    real_path_open = Path.open
    opened: list[str] = []

    def guard(target: Any) -> None:
        name = str(target)
        opened.append(name)
        if "ground_truth" in name:
            raise AssertionError(f"inference opened ground truth: {name}")

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        guard(file)
        return real_open(file, *args, **kwargs)

    def guarded_path_open(self: Path, *args: Any, **kwargs: Any) -> io.IOBase:
        guard(self)
        return real_path_open(self, *args, **kwargs)  # type: ignore[return-value]

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    run_dataset(noisy_dataset, tmp_path / "guarded.jsonl", engine=InferenceEngine())
    assert any("observed" in name for name in opened)


def test_predictions_identical_without_ground_truth(noisy_dataset: Path, tmp_path: Path) -> None:
    observed_only = tmp_path / "observed_only"
    shutil.copytree(noisy_dataset / "observed", observed_only / "observed")
    with_truth, without_truth = tmp_path / "with.jsonl", tmp_path / "without.jsonl"
    run_dataset(noisy_dataset, with_truth)
    run_dataset(observed_only, without_truth)
    assert with_truth.read_bytes() == without_truth.read_bytes()


def test_predictions_do_not_echo_hidden_fields(noisy_dataset: Path, tmp_path: Path) -> None:
    out = tmp_path / "p.jsonl"
    run_dataset(noisy_dataset, out)
    text = out.read_text(encoding="utf-8")
    for hidden in ("canonical_department", "hierarchy_depth", "noise_applied", "pos_", "dept_"):
        assert hidden not in text
