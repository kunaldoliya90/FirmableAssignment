# Risk-coverage analysis: what precision would an engine get by answering only above a threshold
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orggraph_dataset.evaluation.edge_metrics import safe_div


@dataclass
class RiskCoverage:
    thresholds: list[float]
    answered: dict[float, int] = field(default_factory=dict)
    correct: dict[float, int] = field(default_factory=dict)
    total_current: int = 0

    def __post_init__(self) -> None:
        for t in self.thresholds:
            self.answered.setdefault(t, 0)
            self.correct.setdefault(t, 0)

    def record(self, confidence: float | None, correct: bool | None, is_current: bool) -> None:
        if is_current:
            self.total_current += 1
        if correct is None or confidence is None:
            return
        for t in self.thresholds:
            if confidence >= t:
                self.answered[t] += 1
                self.correct[t] += int(correct)

    def to_dict(self) -> list[dict[str, Any]]:
        rows = []
        for t in self.thresholds:
            precision = safe_div(self.correct[t], self.answered[t])
            coverage = safe_div(self.answered[t], self.total_current)
            rows.append(
                {
                    "threshold": t,
                    "answered": self.answered[t],
                    "precision": None if precision is None else round(precision, 6),
                    "coverage": None if coverage is None else round(coverage, 6),
                }
            )
        return rows
