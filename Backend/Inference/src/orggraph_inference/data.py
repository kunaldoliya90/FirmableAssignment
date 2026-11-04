# Observed-only dataset access
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from orggraph_dataset.constants import OBSERVED_DIR, OBSERVED_FILES, SPLITS
from orggraph_dataset.schemas import EmployeeObservation, ObservedCompany, ObservedEmployee


class ObservedDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class ObservedCompanyData:
    company: ObservedCompany
    employees: list[ObservedEmployee]
    observations: list[EmployeeObservation]


@dataclass(frozen=True)
class _Span:
    start: int
    end: int


class ObservedDatasetReader:
    def __init__(self, dataset_dir: Path) -> None:
        self.root = Path(dataset_dir)
        if "ground_truth" in self.root.parts:
            raise ObservedDataError("the inference reader must be given the dataset root, not ground truth")
        if not (self.root / OBSERVED_DIR).is_dir():
            raise ObservedDataError(f"{self.root} has no '{OBSERVED_DIR}/' directory")
        self._index: dict[str, dict[str, dict[str, _Span]]] = {}
        self._company_split: dict[str, str] = {}

    def splits(self) -> list[str]:
        return [s for s in SPLITS if (self.root / OBSERVED_DIR / s).is_dir()]

    def path(self, split: str, kind: str) -> Path:
        return self.root / OBSERVED_DIR / split / OBSERVED_FILES[kind]

    def _build_index(self, split: str) -> dict[str, dict[str, _Span]]:
        if split in self._index:
            return self._index[split]
        spans: dict[str, dict[str, _Span]] = {}
        for kind in OBSERVED_FILES:
            path = self.path(split, kind)
            if not path.exists():
                continue
            with path.open("rb") as handle:
                offset = 0
                current: str | None = None
                start = 0
                for line in handle:
                    if line.strip():
                        company_id = _company_of(line)
                        if company_id != current:
                            if current is not None:
                                spans.setdefault(current, {})[kind] = _Span(start, offset)
                            current, start = company_id, offset
                    offset += len(line)
                if current is not None:
                    spans.setdefault(current, {})[kind] = _Span(start, offset)
        for company_id in spans:
            self._company_split[company_id] = split
        self._index[split] = spans
        return spans

    def company_ids(self, split: str) -> list[str]:
        return list(self._build_index(split))

    def split_of(self, company_id: str) -> str | None:
        if company_id not in self._company_split:
            for split in self.splits():
                self._build_index(split)
        return self._company_split.get(company_id)

    def _read_span(self, split: str, kind: str, span: _Span | None) -> list[dict[str, object]]:
        if span is None:
            return []
        with self.path(split, kind).open("rb") as handle:
            handle.seek(span.start)
            data = handle.read(span.end - span.start)
        return [json.loads(line) for line in data.splitlines() if line.strip()]

    def load_company(self, company_id: str, split: str | None = None) -> ObservedCompanyData:
        split = split or self.split_of(company_id)
        if split is None:
            raise ObservedDataError(f"company {company_id} not found in {self.root}")
        spans = self._build_index(split).get(company_id)
        if spans is None:
            raise ObservedDataError(f"company {company_id} not found in split {split}")
        companies = self._read_span(split, "companies", spans.get("companies"))
        if len(companies) != 1:
            raise ObservedDataError(f"company {company_id}: expected one company row")
        return ObservedCompanyData(
            company=ObservedCompany.model_validate(companies[0]),
            employees=[
                ObservedEmployee.model_validate(r)
                for r in self._read_span(split, "employees", spans.get("employees"))
            ],
            observations=[
                EmployeeObservation.model_validate(r)
                for r in self._read_span(split, "observations", spans.get("observations"))
            ],
        )

    def iter_companies(self, split: str) -> Iterator[ObservedCompanyData]:
        for company_id in self.company_ids(split):
            yield self.load_company(company_id, split)

    def iter_company_rows(self, split: str) -> Iterator[ObservedCompany]:
        path = self.path(split, "companies")
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield ObservedCompany.model_validate_json(line)


_COMPANY_ID = re.compile(rb'"company_id"\s*:\s*"([^"]+)"')


def _company_of(line: bytes) -> str:
    match = _COMPANY_ID.search(line)
    if match:
        return match.group(1).decode("utf-8")
    return str(json.loads(line)["company_id"])
