# Streaming JSONL export
from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel

from orggraph_dataset.constants import (
    GROUND_TRUTH_DIR,
    GROUND_TRUTH_FILES,
    METADATA_DIR,
    OBSERVED_DIR,
    OBSERVED_FILES,
    SPLITS,
)
from orggraph_dataset.schemas import CompanyRecords
from orggraph_dataset.utils.jsonl import JsonlWriter


class OutputDirectoryError(RuntimeError):
    pass


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    managed = [output_dir / OBSERVED_DIR, output_dir / GROUND_TRUTH_DIR, output_dir / METADATA_DIR]
    existing = [p for p in managed if p.exists()]
    if existing and not overwrite:
        raise OutputDirectoryError(f"{output_dir} already contains a dataset; pass --overwrite to replace it")
    for path in existing:
        shutil.rmtree(path)
    output_dir.mkdir(parents=True, exist_ok=True)


def _dump(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json")


class DatasetExporter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self._writers: dict[tuple[str, str, str], JsonlWriter] = {}
        for split in SPLITS:
            for kind, name in OBSERVED_FILES.items():
                self._writers[(OBSERVED_DIR, split, kind)] = JsonlWriter(
                    output_dir / OBSERVED_DIR / split / name
                )
            for kind, name in GROUND_TRUTH_FILES.items():
                self._writers[(GROUND_TRUTH_DIR, split, kind)] = JsonlWriter(
                    output_dir / GROUND_TRUTH_DIR / split / name
                )

    def _writer(self, tree: str, split: str, kind: str) -> JsonlWriter:
        return self._writers[(tree, split, kind)]

    def write(self, records: CompanyRecords) -> None:
        split = records.company.split.value
        obs = OBSERVED_DIR
        gt = GROUND_TRUTH_DIR
        self._writer(obs, split, "companies").write(_dump(records.company.to_observed()))
        self._writer(obs, split, "employees").write_many(_dump(e) for e in records.observed_employees)
        self._writer(obs, split, "observations").write_many(_dump(o) for o in records.observations)

        self._writer(gt, split, "companies").write(_dump(records.company))
        self._writer(gt, split, "departments").write_many(_dump(d) for d in records.departments)
        self._writer(gt, split, "positions").write_many(_dump(p) for p in records.positions)
        self._writer(gt, split, "canonical_roles").write_many(_dump(e) for e in records.employees)
        self._writer(gt, split, "reporting_edges").write_many(_dump(e) for e in records.reporting_edges)
        self._writer(gt, split, "secondary_edges").write_many(_dump(e) for e in records.secondary_edges)
        self._writer(gt, split, "observation_labels").write_many(
            _dump(lbl) for lbl in records.observation_labels
        )
        self._writer(gt, split, "departed_employees").write_many(_dump(d) for d in records.departed_employees)

    def flush(self) -> None:
        for writer in self._writers.values():
            writer.flush()

    def close(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for writer in self._writers.values():
            writer.close()
            counts[writer.path.relative_to(self.output_dir).as_posix()] = writer.count
        return counts
