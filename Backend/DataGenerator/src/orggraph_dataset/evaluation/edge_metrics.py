# Edge-level metrics for primary reporting lines
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


def safe_div(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


@dataclass
class EdgeCounts:
    employees: int = 0
    true_edges: int = 0
    roots: int = 0
    predicted: int = 0
    correct: int = 0
    wrong: int = 0
    wrong_on_root: int = 0
    wrong_cross_company: int = 0
    abstained: int = 0
    missing_predictions: int = 0
    departed_evaluated: int = 0
    departed_predicted: int = 0

    def add(self, other: EdgeCounts) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))

    def record_current(
        self, true_manager: str | None, predicted: str | None, has_row: bool, cross_company: bool
    ) -> bool | None:
        self.employees += 1
        if true_manager is None:
            self.roots += 1
        else:
            self.true_edges += 1
        if predicted is None:
            self.abstained += 1
            if not has_row:
                self.missing_predictions += 1
            return None
        self.predicted += 1
        if true_manager is not None and predicted == true_manager:
            self.correct += 1
            return True
        self.wrong += 1
        if true_manager is None:
            self.wrong_on_root += 1
        if cross_company:
            self.wrong_cross_company += 1
        return False

    def record_departed(self, predicted: str | None) -> bool | None:
        self.departed_evaluated += 1
        if predicted is None:
            return None
        self.predicted += 1
        self.wrong += 1
        self.departed_predicted += 1
        return False

    def metrics(self, penalty: float) -> dict[str, Any]:
        precision = safe_div(self.correct, self.predicted)
        recall = safe_div(self.correct, self.true_edges)
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and (precision + recall) > 0
            else (0.0 if precision is not None and recall is not None else None)
        )
        answered_current = self.employees - self.abstained
        penalized = safe_div(self.correct - penalty * self.wrong, self.true_edges)
        return {
            "edge_precision": _round(precision),
            "edge_recall": _round(recall),
            "edge_f1": _round(f1),
            "coverage": _round(safe_div(answered_current, self.employees)),
            "abstention_rate": _round(safe_div(self.abstained, self.employees)),
            "wrong_edge_rate": _round(safe_div(self.wrong, self.predicted)),
            "penalized_score": _round(penalized),
            "counts": {f.name: getattr(self, f.name) for f in fields(self)},
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)
