# Reload an exported dataset, streaming one company at a time
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orggraph_dataset.constants import (
    GROUND_TRUTH_DIR,
    GROUND_TRUTH_FILES,
    MANIFEST_FILE,
    METADATA_DIR,
    OBSERVED_DIR,
    OBSERVED_FILES,
    SPLIT_MANIFEST_FILE,
    SPLITS,
)
from orggraph_dataset.utils.jsonl import iter_jsonl, read_json


class DatasetLayoutError(RuntimeError):
    pass


class _ChunkReader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._rows = iter_jsonl(path) if path.exists() else iter(())
        self._peek: dict[str, Any] | None = next(self._rows, None)
        self.seen: set[str] = set()

    def take(self, company_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while self._peek is not None and self._peek.get("company_id") == company_id:
            rows.append(self._peek)
            self._peek = next(self._rows, None)
        if rows:
            if company_id in self.seen:
                raise DatasetLayoutError(f"{self.path}: rows for {company_id} are not contiguous")
            self.seen.add(company_id)
        return rows

    def leftover(self) -> dict[str, Any] | None:
        return self._peek


@dataclass
class RawCompanyChunk:
    split: str
    company_id: str
    observed: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ground_truth: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


class DatasetReader:
    def __init__(self, dataset_dir: Path) -> None:
        self.root = dataset_dir
        if not (dataset_dir / OBSERVED_DIR).is_dir() or not (dataset_dir / GROUND_TRUTH_DIR).is_dir():
            raise DatasetLayoutError(
                f"{dataset_dir} is not a dataset directory "
                f"(expected '{OBSERVED_DIR}/' and '{GROUND_TRUTH_DIR}/')"
            )

    def observed_path(self, split: str, kind: str) -> Path:
        return self.root / OBSERVED_DIR / split / OBSERVED_FILES[kind]

    def ground_truth_path(self, split: str, kind: str) -> Path:
        return self.root / GROUND_TRUTH_DIR / split / GROUND_TRUTH_FILES[kind]

    def splits(self) -> list[str]:
        return [s for s in SPLITS if (self.root / OBSERVED_DIR / s).is_dir()]

    def manifest(self) -> dict[str, Any] | None:
        path = self.root / METADATA_DIR / MANIFEST_FILE
        return read_json(path) if path.exists() else None

    def split_manifest(self) -> dict[str, Any] | None:
        path = self.root / METADATA_DIR / SPLIT_MANIFEST_FILE
        return read_json(path) if path.exists() else None

    def iter_observed(self, split: str, kind: str) -> Iterator[dict[str, Any]]:
        path = self.observed_path(split, kind)
        return iter_jsonl(path) if path.exists() else iter(())

    def iter_ground_truth(self, split: str, kind: str) -> Iterator[dict[str, Any]]:
        path = self.ground_truth_path(split, kind)
        return iter_jsonl(path) if path.exists() else iter(())

    def iter_company_chunks(self, split: str) -> Iterator[RawCompanyChunk]:
        observed = {k: _ChunkReader(self.observed_path(split, k)) for k in OBSERVED_FILES if k != "companies"}
        truth = {k: _ChunkReader(self.ground_truth_path(split, k)) for k in GROUND_TRUTH_FILES}
        for company in self.iter_observed(split, "companies"):
            company_id = str(company.get("company_id"))
            chunk = RawCompanyChunk(split=split, company_id=company_id)
            chunk.observed["companies"] = [company]
            for kind, reader in observed.items():
                chunk.observed[kind] = reader.take(company_id)
            for kind, reader in truth.items():
                chunk.ground_truth[kind] = reader.take(company_id)
            yield chunk
        for reader in (*observed.values(), *truth.values()):
            row = reader.leftover()
            if row is not None:
                raise DatasetLayoutError(
                    f"{reader.path}: row for company {row.get('company_id')} has no matching company "
                    "record or is out of order"
                )
