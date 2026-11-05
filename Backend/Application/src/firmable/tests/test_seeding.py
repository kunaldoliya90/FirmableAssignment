# Startup seeding of baked-in artifacts: copy missing, upgrade untouched, never overwrite runtime output
from __future__ import annotations

from pathlib import Path

from firmable.core.seeding import seed_artifacts


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_seed_copies_upgrades_and_keeps(tmp_path: Path) -> None:
    seed, target = tmp_path / "seed", tmp_path / "artifacts"
    _write(seed / "ds/predictions/test.jsonl", "v1")
    _write(seed / "ds/evaluations/a.json", "eval-a")
    assert seed_artifacts(seed, target) == {"copied": 2, "upgraded": 0, "kept": 0}
    assert (target / "ds/predictions/test.jsonl").read_text(encoding="utf-8") == "v1"

    # runtime output next to the seed survives, and a restart with the same seed changes nothing
    _write(target / "ds/evaluations/runtime.json", "mine")
    assert seed_artifacts(seed, target) == {"copied": 0, "upgraded": 0, "kept": 2}

    # a new deploy upgrades files nobody touched since the last seed
    _write(seed / "ds/predictions/test.jsonl", "v2")
    assert seed_artifacts(seed, target)["upgraded"] == 1
    assert (target / "ds/predictions/test.jsonl").read_text(encoding="utf-8") == "v2"

    # ...but never a file that was regenerated at runtime
    _write(target / "ds/predictions/test.jsonl", "rerun at runtime")
    _write(seed / "ds/predictions/test.jsonl", "v3")
    assert seed_artifacts(seed, target)["kept"] == 2
    assert (target / "ds/predictions/test.jsonl").read_text(encoding="utf-8") == "rerun at runtime"
    assert (target / "ds/evaluations/runtime.json").read_text(encoding="utf-8") == "mine"


def test_missing_seed_dir_is_a_no_op(tmp_path: Path) -> None:
    assert seed_artifacts(tmp_path / "absent", tmp_path / "artifacts") == {
        "copied": 0,
        "upgraded": 0,
        "kept": 0,
    }
