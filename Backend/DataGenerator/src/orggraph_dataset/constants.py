# Project-wide constants: level orderings, split names, file layout and leakage rules
from __future__ import annotations

SCHEMA_VERSION = "1.0.0"

SENIORITY_ORDER: tuple[str, ...] = (
    "intern",
    "junior",
    "ic",
    "senior_ic",
    "staff",
    "principal",
    "manager",
    "senior_manager",
    "director",
    "senior_director",
    "vp",
    "svp",
    "executive",
    "c_level",
)
SENIORITY_RANK: dict[str, int] = {level: rank for rank, level in enumerate(SENIORITY_ORDER)}
IC_LEVELS: tuple[str, ...] = SENIORITY_ORDER[:6]
MANAGEMENT_LEVELS: tuple[str, ...] = (
    "manager",
    "senior_manager",
    "director",
    "senior_director",
    "vp",
    "svp",
)
EXECUTIVE_LEVELS: tuple[str, ...] = ("executive", "c_level")

SIZE_SEGMENTS: tuple[str, ...] = ("small", "mid_small", "mid_market", "large", "enterprise")
SPLITS: tuple[str, ...] = ("train", "validation", "test", "challenge")
SOURCES: tuple[str, ...] = (
    "hr_export",
    "company_directory",
    "public_profile",
    "internal_directory",
    "historical_snapshot",
)
ARCHETYPES: tuple[str, ...] = (
    "functional",
    "product_based",
    "regional",
    "business_unit",
    "flat_startup",
    "enterprise",
    "matrix",
)

NULLABLE_OBSERVATION_FIELDS: tuple[str, ...] = (
    "observed_title",
    "observed_department",
    "observed_job_family",
    "observed_location",
    "source",
    "observed_at",
)

OBSERVED_DIR = "observed"
GROUND_TRUTH_DIR = "ground_truth"
METADATA_DIR = "metadata"

OBSERVED_FILES: dict[str, str] = {
    "companies": "companies.jsonl",
    "employees": "employees.jsonl",
    "observations": "observations.jsonl",
}
GROUND_TRUTH_FILES: dict[str, str] = {
    "companies": "companies.jsonl",
    "departments": "departments.jsonl",
    "positions": "positions.jsonl",
    "canonical_roles": "canonical_roles.jsonl",
    "reporting_edges": "reporting_edges.jsonl",
    "secondary_edges": "secondary_edges.jsonl",
    "observation_labels": "observation_labels.jsonl",
    "departed_employees": "departed_employees.jsonl",
}
MANIFEST_FILE = "dataset_manifest.json"
GENERATION_CONFIG_FILE = "generation_config.json"
SPLIT_MANIFEST_FILE = "split_manifest.json"
GENERATION_SUMMARY_FILE = "generation_summary.json"
VALIDATION_REPORT_FILE = "validation_report.json"

FORBIDDEN_OBSERVED_FIELDS: frozenset[str] = frozenset(
    {
        "manager_employee_id",
        "manager_id",
        "canonical_title",
        "canonical_department",
        "organizational_level",
        "hierarchy_depth",
        "parent_position_id",
        "position_id",
        "department_id",
        "parent_department_id",
        "ground_truth_source",
        "noise_applied",
        "relationship_type",
        "reporting_edges",
        "seniority_level",
        "job_family",
        "org_archetype",
        "generation_seed",
        "noise_profile",
        "split",
        "is_stale",
    }
)

OBSERVED_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "companies": frozenset(
        {
            "company_id",
            "company_name",
            "industry",
            "employee_count",
            "company_size_segment",
            "headquarters",
            "operating_regions",
        }
    ),
    "employees": frozenset(
        {"employee_id", "company_id", "full_name", "first_name", "last_name", "employment_type"}
    ),
    "observations": frozenset(
        {
            "observation_id",
            "employee_id",
            "company_id",
            "observed_title",
            "observed_department",
            "observed_job_family",
            "observed_location",
            "source",
            "observed_at",
            "employment_status",
            "historical_manager_id",
            "missing_fields",
        }
    ),
}

GROUND_TRUTH_ID_PREFIXES: tuple[str, ...] = ("pos_", "dept_")
