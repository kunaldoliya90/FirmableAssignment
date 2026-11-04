# Confidence calibration over answered (non-null) predictions: reliability bins, ECE, MCE, Brier
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Calibration:
    bins: int
    counts: list[int] = field(default_factory=list)
    confidence_sum: list[float] = field(default_factory=list)
    correct_sum: list[int] = field(default_factory=list)
    brier_sum: float = 0.0

    def __post_init__(self) -> None:
        self.counts = [0] * self.bins
        self.confidence_sum = [0.0] * self.bins
        self.correct_sum = [0] * self.bins

    def record(self, confidence: float, correct: bool) -> None:
        index = min(int(confidence * self.bins), self.bins - 1)
        self.counts[index] += 1
        self.confidence_sum[index] += confidence
        self.correct_sum[index] += int(correct)
        self.brier_sum += (confidence - float(correct)) ** 2

    @property
    def total(self) -> int:
        return sum(self.counts)

    def to_dict(self) -> dict[str, Any]:
        total = self.total
        reliability = []
        ece = 0.0
        mce = 0.0
        for i in range(self.bins):
            n = self.counts[i]
            row: dict[str, Any] = {
                "bin": [round(i / self.bins, 4), round((i + 1) / self.bins, 4)],
                "count": n,
            }
            if n:
                mean_conf = self.confidence_sum[i] / n
                accuracy = self.correct_sum[i] / n
                gap = abs(mean_conf - accuracy)
                ece += gap * n / total
                mce = max(mce, gap)
                row.update(
                    mean_confidence=round(mean_conf, 6),
                    accuracy=round(accuracy, 6),
                    gap=round(gap, 6),
                )
            reliability.append(row)
        return {
            "answered_predictions": total,
            "expected_calibration_error": round(ece, 6) if total else None,
            "max_calibration_error": round(mce, 6) if total else None,
            "brier_score": round(self.brier_sum / total, 6) if total else None,
            "reliability": reliability,
        }
