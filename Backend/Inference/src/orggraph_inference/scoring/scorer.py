# Relationship scoring and confidence estimation
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from orggraph_inference.config import InferenceConfig, ScoringWeights
from orggraph_inference.features.profiles import EmployeeProfile
from orggraph_inference.features.relationship import RelationshipFeatures, relationship_features


@dataclass(frozen=True)
class ScoredCandidate:
    employee_id: str
    score: float
    probability: float
    features: RelationshipFeatures


@dataclass(frozen=True)
class ScoredEmployee:
    employee_id: str
    candidates: list[ScoredCandidate]
    abstain_probability: float
    profile_quality: float


def linear_score(f: RelationshipFeatures, w: ScoringWeights) -> float:
    score = w.level_step * f.level_steps
    score += w.same_department * f.same_department
    score += w.same_subdepartment * f.same_subdepartment
    score += w.subdepartment_conflict * f.subdepartment_conflict
    score += w.department_conflict * f.department_conflict
    score += w.same_family * f.same_family
    score += w.manages_family * f.manages_family
    score += w.same_segment * f.same_segment
    score += w.segment_conflict * f.segment_conflict
    score += w.same_region * f.same_region
    score += w.same_city * f.same_city
    score += w.historical_manager * f.historical_manager
    score += w.executive_owns_department * f.executive_owns_department
    score += w.executive_wrong_function * f.executive_wrong_function
    score += w.ceo_for_top_level * f.ceo_for_top_level
    score += w.ceo_for_lower_level * f.ceo_for_lower_level
    score += w.candidate_generic_title * f.candidate_generic_title
    score += w.candidate_uncertain_seniority * f.candidate_uncertain_seniority
    score += w.candidate_not_manager * f.candidate_not_manager
    score += w.level_step_exact.get(step_bucket(f.level_steps), 0.0)
    if f.employee_is_ic and f.candidate_seniority:
        score += w.ic_reports_to.get(f.candidate_seniority, 0.0)
    return score


def step_bucket(steps: float) -> str:
    return "3+" if steps >= 3 else str(int(steps))


# (weight name, feature name) for every scalar term of linear_score
SCALAR_TERMS: tuple[tuple[str, str], ...] = (
    ("level_step", "level_steps"),
    ("same_department", "same_department"),
    ("same_subdepartment", "same_subdepartment"),
    ("subdepartment_conflict", "subdepartment_conflict"),
    ("department_conflict", "department_conflict"),
    ("same_family", "same_family"),
    ("manages_family", "manages_family"),
    ("same_segment", "same_segment"),
    ("segment_conflict", "segment_conflict"),
    ("same_region", "same_region"),
    ("same_city", "same_city"),
    ("historical_manager", "historical_manager"),
    ("executive_owns_department", "executive_owns_department"),
    ("executive_wrong_function", "executive_wrong_function"),
    ("ceo_for_top_level", "ceo_for_top_level"),
    ("ceo_for_lower_level", "ceo_for_lower_level"),
    ("candidate_generic_title", "candidate_generic_title"),
    ("candidate_uncertain_seniority", "candidate_uncertain_seniority"),
    ("candidate_not_manager", "candidate_not_manager"),
)


# The inputs of linear_score keyed by weight name; dict weights use `name.key`. Used by offline training.
def feature_terms(f: RelationshipFeatures) -> dict[str, float]:
    terms = {weight: float(getattr(f, feature)) for weight, feature in SCALAR_TERMS}
    terms[f"level_step_exact.{step_bucket(f.level_steps)}"] = 1.0
    if f.employee_is_ic and f.candidate_seniority:
        terms[f"ic_reports_to.{f.candidate_seniority}"] = 1.0
    return terms


def weights_from_terms(values: dict[str, float], base: ScoringWeights | None = None) -> ScoringWeights:
    update: dict[str, object] = {}
    exact: dict[str, float] = {}
    ic: dict[str, float] = {}
    for name, value in values.items():
        group, _, key = name.partition(".")
        if group == "level_step_exact":
            exact[key] = value
        elif group == "ic_reports_to":
            ic[key] = value
        else:
            update[name] = value
    return (base or ScoringWeights()).model_copy(
        update={**update, "level_step_exact": exact, "ic_reports_to": ic}
    )


def profile_quality(profile: EmployeeProfile) -> float:
    quality = 0.5 + 0.3 * profile.seniority_confidence + 0.2 * min(profile.department_confidence * 1.5, 1.0)
    if profile.generic_title:
        quality *= 0.8
    return min(quality, 1.0)


class RelationshipScorer:
    def __init__(self, config: InferenceConfig) -> None:
        self.config = config

    def score(
        self,
        employee: EmployeeProfile,
        candidates: list[EmployeeProfile],
        executive_departments: dict[str, set[str]],
        present_ranks: Sequence[float] = (),
    ) -> ScoredEmployee:
        features = [
            relationship_features(employee, c, executive_departments, present_ranks) for c in candidates
        ]
        raw = [linear_score(f, self.config.weights) for f in features]
        temperature = self.config.softmax_temperature
        logits = [s / temperature for s in raw] + [self.config.abstain_score / temperature]
        peak = max(logits)
        exps = [math.exp(x - peak) for x in logits]
        total = sum(exps)
        probs = [e / total for e in exps]
        scored = [
            ScoredCandidate(c.employee_id, round(s, 4), p, f)
            for c, s, p, f in zip(candidates, raw, probs[:-1], features, strict=True)
        ]
        scored.sort(key=lambda c: (-c.probability, c.employee_id))
        return ScoredEmployee(employee.employee_id, scored, probs[-1], profile_quality(employee))
