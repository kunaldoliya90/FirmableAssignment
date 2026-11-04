# Validation issue collection
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from orggraph_dataset.config import OrgGraphConfig

MAX_STORED_ISSUES = 500


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    company_id: str | None = None
    record_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def __str__(self) -> str:
        where = " ".join(p for p in (self.company_id, self.record_id) if p)
        return f"[{self.code}] {where + ': ' if where else ''}{self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    issue_counts: Counter[str] = field(default_factory=Counter)
    checks: Counter[str] = field(default_factory=Counter)
    stats: dict[str, Any] = field(default_factory=dict)

    def error(
        self, code: str, message: str, company_id: str | None = None, record_id: str | None = None
    ) -> None:
        self.issue_counts[code] += 1
        if len(self.issues) < MAX_STORED_ISSUES:
            self.issues.append(ValidationIssue(code, message, company_id, record_id))

    def check(self, name: str, n: int = 1) -> None:
        self.checks[name] += n

    @property
    def error_count(self) -> int:
        return sum(self.issue_counts.values())

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def merge(self, other: ValidationReport) -> None:
        for issue in other.issues:
            if len(self.issues) < MAX_STORED_ISSUES:
                self.issues.append(issue)
        self.issue_counts.update(other.issue_counts)
        self.checks.update(other.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": self.error_count,
            "issue_counts": dict(sorted(self.issue_counts.items())),
            "checks": dict(sorted(self.checks.items())),
            "stats": self.stats,
            "issues": [i.to_dict() for i in self.issues],
            "issues_truncated": self.error_count > len(self.issues),
        }

    def summary_lines(self, limit: int = 20) -> list[str]:
        lines = [f"{code}: {count}" for code, count in sorted(self.issue_counts.items())]
        lines += [str(issue) for issue in self.issues[:limit]]
        return lines


@dataclass(frozen=True)
class ValidationContext:
    industry_names: frozenset[str]
    segment_bounds: dict[str, tuple[int, int]]
    min_employees_per_company: int
    reference_date: date

    @classmethod
    def from_config(
        cls, config: OrgGraphConfig, min_employees_per_company: int | None = None
    ) -> ValidationContext:
        return cls(
            industry_names=frozenset(i.name for i in config.industries.industries.values()),
            segment_bounds={k: (s.min, s.max) for k, s in config.company_sizes.segments.items()},
            min_employees_per_company=min_employees_per_company or config.dataset.min_employees_per_company,
            reference_date=config.dataset.reference_date,
        )


@dataclass
class GlobalIdRegistry:
    company_ids: set[str] = field(default_factory=set)
    employee_ids: set[str] = field(default_factory=set)
    observation_ids: set[str] = field(default_factory=set)
