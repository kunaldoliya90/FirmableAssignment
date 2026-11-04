# Prediction file schema and loader (JSONL, one prediction per employee)
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from orggraph_dataset.utils.jsonl import JsonlDecodeError, iter_jsonl


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: str
    employee_id: str
    predicted_manager_id: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_self_prediction(self) -> Prediction:
        if self.predicted_manager_id is not None and self.predicted_manager_id == self.employee_id:
            raise ValueError("an employee cannot be predicted to report to themselves")
        return self

    @property
    def abstained(self) -> bool:
        return self.predicted_manager_id is None


class PredictionFileError(ValueError):
    pass


PredictionKey = tuple[str, str]


def load_predictions(path: Path) -> dict[PredictionKey, Prediction]:
    if not path.is_file():
        raise PredictionFileError(f"prediction file not found: {path}")
    predictions: dict[PredictionKey, Prediction] = {}
    line = 0
    try:
        for line, row in enumerate(iter_jsonl(path), start=1):
            try:
                prediction = Prediction.model_validate(row)
            except ValidationError as exc:
                first = exc.errors()[0]
                where = ".".join(str(p) for p in first["loc"]) or "<row>"
                raise PredictionFileError(f"{path}: prediction #{line}: {where}: {first['msg']}") from None
            key = (prediction.company_id, prediction.employee_id)
            if key in predictions:
                raise PredictionFileError(f"{path}: duplicate prediction for {key[0]}/{key[1]} (#{line})")
            predictions[key] = prediction
    except JsonlDecodeError as exc:
        raise PredictionFileError(str(exc)) from exc
    return predictions
