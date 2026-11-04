# Inference request and prediction summary models
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CompanyInferenceOut(BaseModel):
    company_id: str
    employees: int
    predicted_edges: int
    abstentions: int
    departed_detected: int
    root_id: str | None
    decision_reasons: dict[str, int]
    confidence_threshold: float
    elapsed_seconds: float


class SplitInferenceRequest(BaseModel):
    splits: list[str] = Field(default_factory=lambda: ["test"])


class InferenceRunOut(BaseModel):
    split: str
    predictions_file: str
    summary: dict[str, Any]


class OrgNode(BaseModel):
    employee_id: str
    full_name: str
    title: str | None
    seniority: str | None
    department: str | None
    manager_id: str | None
    confidence: float
    direct_reports: int
    subtree_size: int
    depth: int
    children_loaded: bool


class OrgEdge(BaseModel):
    source: str
    target: str
    confidence: float


class OrgChart(BaseModel):
    company_id: str
    root_id: str | None
    focus_id: str | None
    nodes: list[OrgNode]
    edges: list[OrgEdge]
    resolved: int
    unresolved: int
    total_employees: int


class UnresolvedEmployee(BaseModel):
    employee_id: str
    full_name: str
    title: str | None
    seniority: str | None
    department: str | None
    reason: str
    best_candidate_id: str | None
    best_candidate_name: str | None
    best_probability: float
