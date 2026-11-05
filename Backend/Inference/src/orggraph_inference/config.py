# Inference tunables; learned_weights.json (written by `orggraph-infer train`) overrides the hand-set defaults
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LEARNED_WEIGHTS_PATH = Path(__file__).with_name("learned_weights.json")


@lru_cache(maxsize=1)
def learned_settings() -> dict[str, Any]:
    if not LEARNED_WEIGHTS_PATH.is_file():
        return {}
    data: dict[str, Any] = json.loads(LEARNED_WEIGHTS_PATH.read_text(encoding="utf-8"))
    return data


class ScoringWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level_step: float = -1.1
    same_department: float = 2.2
    same_subdepartment: float = 1.6
    subdepartment_conflict: float = -1.2
    department_conflict: float = -2.5
    same_family: float = 0.9
    manages_family: float = 0.6
    same_segment: float = 1.8
    segment_conflict: float = -1.8
    same_region: float = 0.35
    same_city: float = 0.25
    historical_manager: float = 3.5
    executive_owns_department: float = 2.6
    executive_wrong_function: float = -1.5
    ceo_for_top_level: float = 1.5
    ceo_for_lower_level: float = -3.0
    candidate_generic_title: float = -0.4
    candidate_uncertain_seniority: float = -0.6
    candidate_not_manager: float = -3.0
    load_balance: float = -0.03
    # learned only: bonus per exact level gap ("0", "1", "2", "3+") and per manager seniority for IC employees
    level_step_exact: dict[str, float] = Field(default_factory=dict)
    ic_reports_to: dict[str, float] = Field(default_factory=dict)


def _default_weights() -> ScoringWeights:
    learned = learned_settings().get("weights")
    return ScoringWeights.model_validate(learned) if learned else ScoringWeights()


class InferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_reliability: dict[str, float] = Field(
        default_factory=lambda: {
            "hr_export": 1.0,
            "internal_directory": 0.8,
            "company_directory": 0.65,
            "public_profile": 0.4,
            "historical_snapshot": 0.25,
            "unknown": 0.35,
        }
    )
    recency_half_life_days: float = 365.0
    departed_threshold: float = 0.5

    fuzzy_title_threshold: float = 0.84
    fuzzy_department_threshold: float = 0.86

    max_candidates: int = Field(default=25, ge=1)
    abstain_score: float = Field(default_factory=lambda: learned_settings().get("abstain_score", 0.6))
    softmax_temperature: float = 1.0
    confidence_threshold: float = Field(
        default_factory=lambda: learned_settings().get("confidence_threshold", 0.55), ge=0.0, le=1.0
    )
    weights: ScoringWeights = Field(default_factory=_default_weights)

    span_caps: dict[str, int] = Field(
        default_factory=lambda: {
            "manager": 22,
            "senior_manager": 10,
            "director": 12,
            "senior_director": 10,
            "vp": 12,
            "svp": 10,
            "executive": 12,
            "c_level": 16,
        }
    )
    optimization_rounds: int = Field(default=3, ge=0)
