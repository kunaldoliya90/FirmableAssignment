# Configuration models and loader
from __future__ import annotations

import copy
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from orggraph_dataset.constants import (
    ARCHETYPES,
    IC_LEVELS,
    MANAGEMENT_LEVELS,
    SENIORITY_ORDER,
    SIZE_SEGMENTS,
    SOURCES,
    SPLITS,
)


class ConfigError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Probability = float


class SegmentConfig(_Strict):
    label: str
    min: int = Field(ge=1)
    max: int = Field(ge=1)
    default_count: int = Field(ge=0)


class CompanySizesConfig(_Strict):
    segments: dict[str, SegmentConfig]
    keep_min_per_segment: int = Field(default=2, ge=0)
    within_segment_skew: float = Field(default=1.0, ge=1.0)


class NamingConfig(_Strict):
    first_parts: list[str] = Field(min_length=1)
    second_parts: list[str] = Field(min_length=1)


class IndustryConfig(_Strict):
    name: str
    weight: float = Field(gt=0)
    name_suffixes: list[str] = Field(min_length=1)
    size_weights: dict[str, float]
    archetype_weights: dict[str, float]
    region_weights: dict[str, float]
    business_units: list[str] = Field(min_length=1)
    product_lines: list[str] = Field(min_length=1)
    executive_overrides: dict[str, str] = Field(default_factory=dict)
    departments: dict[str, tuple[Probability, float]]


class IndustriesConfig(_Strict):
    naming: NamingConfig
    industries: dict[str, IndustryConfig]


class SubDepartmentConfig(_Strict):
    key: str
    name: str
    weight: float = Field(default=1.0, gt=0)
    min_parent_headcount: int = Field(ge=1)
    families: dict[str, float] | None = None
    abbreviations: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class DepartmentConfig(_Strict):
    name: str
    abbreviations: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    families: dict[str, float] = Field(min_length=1)
    management_family: str | None = None
    executive: str | None = None
    tags: list[Literal["line", "product_line", "regional", "corporate", "executive"]]
    min_company_employees: int = 0
    subdepartments: list[SubDepartmentConfig] = Field(default_factory=list)

    @property
    def primary_family(self) -> str:
        if self.management_family:
            return self.management_family
        return max(self.families, key=lambda k: self.families[k])


class DepartmentsConfig(_Strict):
    departments: dict[str, DepartmentConfig]


class JobFamilyConfig(_Strict):
    name: str
    aliases: list[str] = Field(default_factory=list)
    ic_role: str
    ic_abbrev: str
    function: str
    function_abbrev: str
    ic_levels: list[str] = Field(default_factory=lambda: list(IC_LEVELS))
    management: bool = True
    industries: list[str] | None = None
    legacy_titles: dict[str, list[str]] = Field(default_factory=dict)


class JobFamiliesConfig(_Strict):
    families: dict[str, JobFamilyConfig]


class SeniorityLevelConfig(_Strict):
    key: str
    label: str
    tier: int = Field(ge=0)
    management: bool
    executive: bool


class TitleOverride(_Strict):
    title: str
    variants: list[str] = Field(default_factory=list)


class ExecutiveRoleConfig(_Strict):
    title: str
    seniority: str
    variants: list[str] = Field(default_factory=list)


class TitleTaxonomyConfig(_Strict):
    seniority_levels: list[SeniorityLevelConfig]
    ladder_patterns: dict[str, str]
    variant_patterns: dict[str, list[str]]
    overrides: dict[str, dict[str, TitleOverride | str]] = Field(default_factory=dict)
    executive_roles: dict[str, ExecutiveRoleConfig]

    def override_for(self, family: str, level: str) -> TitleOverride | None:
        raw = self.overrides.get(family, {}).get(level)
        if raw is None:
            return None
        return TitleOverride(title=raw) if isinstance(raw, str) else raw


class SegmentLayerConfig(_Strict):
    kind: Literal["business_unit", "division", "region", "product_line"]
    head_role: str
    count: tuple[int, int]
    department_tags: list[str] = Field(min_length=1)
    min_headcount: int = Field(ge=2)


class ArchetypeConfig(_Strict):
    description: str = ""
    levels: list[str] = Field(min_length=1)
    level_min_headcount: dict[str, int]
    level_size_scale: float = Field(gt=0)
    span_of_control: dict[str, tuple[int, int]]
    ic_team_size: tuple[int, int]
    manager_max_team_size: int = Field(ge=2)
    large_span_probability: Probability = Field(ge=0, le=1)
    leader_direct_ic_probability: Probability = Field(ge=0, le=1)
    exec_layer_min_employees: int = Field(ge=0)
    exec_min_group_headcount: int = Field(ge=2)
    corporate_head_cap: str
    small_company_head_cap: str
    segmentation: list[SegmentLayerConfig] = Field(default_factory=list)
    secondary_reporting_probability: Probability = Field(ge=0, le=1)
    secondary_member_departments: list[str] = Field(default_factory=list)
    secondary_manager_departments: list[str] = Field(default_factory=list)
    expected_depth: tuple[int, int]
    min_employees: int = Field(ge=1)
    max_employees: int | None = None
    size_weights: dict[str, float]


class ArchetypesConfig(_Strict):
    division_name_patterns: list[str] = Field(min_length=1)
    archetypes: dict[str, ArchetypeConfig]


TITLE_NOISE_OPERATIONS: tuple[str, ...] = (
    "variant",
    "abbreviation",
    "typo",
    "punctuation",
    "capitalization",
    "seniority_removal",
    "truncation",
    "department_suffix",
    "regional_suffix",
    "business_unit_suffix",
    "generic_replacement",
    "legacy_title",
)
DEPARTMENT_NOISE_OPERATIONS: tuple[str, ...] = (
    "abbreviation",
    "alias",
    "parent_department",
    "segment_prefix",
    "case_format",
)
LOCATION_NOISE_OPERATIONS: tuple[str, ...] = ("city_alias", "formatting", "region_instead")
GENERIC_TITLE_TIERS: tuple[str, ...] = ("executive", "vp", "director", "manager", "individual")
REQUIRED_NOISE_PROFILES: tuple[str, ...] = (
    "clean",
    "low_noise",
    "medium_noise",
    "high_noise",
    "enterprise_complexity",
)


class NoiseProfileConfig(_Strict):
    description: str = ""
    title_corruption_probability: Probability = Field(ge=0, le=1)
    max_title_operations: int = Field(ge=1)
    missing_title_probability: Probability = Field(ge=0, le=1)
    missing_department_probability: Probability = Field(ge=0, le=1)
    missing_location_probability: Probability = Field(ge=0, le=1)
    missing_job_family_probability: Probability = Field(ge=0, le=1)
    missing_source_probability: Probability = Field(ge=0, le=1)
    missing_timestamp_probability: Probability = Field(ge=0, le=1)
    stale_observation_probability: Probability = Field(ge=0, le=1)
    source_conflict_probability: Probability = Field(ge=0, le=1)
    department_inconsistency_probability: Probability = Field(ge=0, le=1)
    location_noise_probability: Probability = Field(ge=0, le=1)
    ambiguity_probability: Probability = Field(ge=0, le=1)
    historical_manager_probability: Probability = Field(ge=0, le=1)
    promotion_rate: Probability = Field(ge=0, le=1)
    transfer_rate: Probability = Field(ge=0, le=1)
    departed_employee_rate: Probability = Field(ge=0, le=0.5)
    source_coverage_multiplier: float = Field(gt=0)


class NoiseConfig(_Strict):
    profiles: dict[str, NoiseProfileConfig]
    title_noise_weights: dict[str, float]
    department_noise_weights: dict[str, float]
    location_noise_weights: dict[str, float]
    chained_operation_probability: Probability = Field(ge=0, le=1)
    abbreviations: dict[str, list[str]]
    seniority_markers: list[str]
    generic_titles: dict[str, list[str]]
    department_suffix_formats: list[str] = Field(min_length=1)
    regional_suffix_formats: list[str] = Field(min_length=1)
    segment_prefix_formats: list[str] = Field(min_length=1)
    truncation_max_chars: int = Field(ge=4)


class SourceConfig(_Strict):
    label: str
    coverage: Probability = Field(ge=0, le=1)
    coverage_by_employment_type: dict[str, Probability] = Field(default_factory=dict)
    title_noise_multiplier: float = Field(ge=0)
    missing_department_multiplier: float = Field(ge=0)
    missing_location_multiplier: float = Field(ge=0)
    missing_job_family_multiplier: float = Field(ge=0)
    missing_title_multiplier: float = Field(ge=0)
    stale_multiplier: float = Field(ge=0)
    conflict_multiplier: float = Field(ge=0)
    department_noise_multiplier: float = Field(ge=0)
    location_noise_multiplier: float = Field(ge=0)
    includes_job_family: bool
    reports_employment_status: bool
    always_historical: bool
    provides_historical_manager: bool
    status_unknown_probability: Probability = Field(ge=0, le=1)
    age_days: tuple[int, int]


class SourcesConfig(_Strict):
    sources: dict[str, SourceConfig]
    fallback_source: str
    departed_source_coverage: dict[str, Probability]


class RegionConfig(_Strict):
    name: str
    aliases: list[str] = Field(default_factory=list)
    faker_locales: list[str] = Field(min_length=1)


class CityConfig(_Strict):
    name: str
    country: str
    country_code: str
    region: str
    aliases: list[str] = Field(default_factory=list)


class LocationsConfig(_Strict):
    regions: dict[str, RegionConfig]
    cities: list[CityConfig] = Field(min_length=1)
    operating_regions_by_size: dict[str, tuple[int, int]]
    offices_per_region_by_size: dict[str, tuple[int, int]]


class SplitsConfig(_Strict):
    fractions: dict[str, float]
    challenge_archetype_weights: dict[str, float]
    challenge_size_weights: dict[str, float]
    holdout_industries: list[str] = Field(default_factory=list)


class WorkforceConfig(_Strict):
    ic_seniority_mix: dict[str, float]
    leader_direct_ic_mix: dict[str, float]
    employment_type_mix: dict[str, float]
    mixed_team_probability: Probability = Field(ge=0, le=1)
    min_department_headcount: int = Field(ge=1)
    min_subdepartment_headcount: int = Field(ge=1)
    department_direct_share: float = Field(ge=0, lt=1)
    executive_support_per_employees: int = Field(ge=1)
    executive_support_max: int = Field(ge=0)
    department_weight_jitter: float = Field(ge=0)
    remote_probability: Probability = Field(ge=0, le=1)
    hq_location_probability: Probability = Field(ge=0, le=1)
    on_leave_probability: Probability = Field(ge=0, le=1)


class EvaluationConfig(_Strict):
    wrong_edge_penalty: float = Field(ge=0)
    calibration_bins: int = Field(ge=2)
    confidence_thresholds: list[float]


class DatasetDefaults(_Strict):
    dataset_version: str
    companies: int = Field(ge=1)
    min_employees_per_company: int = Field(ge=1)
    target_employees: int = Field(ge=1)
    size_diversity_multiplier: float = Field(ge=1.0)
    seed: int
    noise_profile: str
    challenge_noise_profile: str
    reference_date: date
    output_dir: str
    batch_size: int = Field(ge=1)
    splits: SplitsConfig
    workforce: WorkforceConfig
    evaluation: EvaluationConfig


class OrgGraphConfig(_Strict):
    dataset: DatasetDefaults
    company_sizes: CompanySizesConfig
    industries: IndustriesConfig
    departments: DepartmentsConfig
    job_families: JobFamiliesConfig
    titles: TitleTaxonomyConfig
    archetypes: ArchetypesConfig
    noise: NoiseConfig
    sources: SourcesConfig
    locations: LocationsConfig

    @model_validator(mode="after")
    def _cross_check(self) -> OrgGraphConfig:
        errors = _cross_reference_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def profile(self, name: str) -> NoiseProfileConfig:
        try:
            return self.noise.profiles[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.noise.profiles))
            raise ConfigError(f"unknown noise profile '{name}' (known: {known})") from exc


CONFIG_FILES: dict[str, str] = {
    "dataset": "dataset_defaults.yaml",
    "company_sizes": "company_sizes.yaml",
    "industries": "industries.yaml",
    "departments": "departments.yaml",
    "job_families": "job_families.yaml",
    "titles": "title_taxonomy.yaml",
    "archetypes": "org_archetypes.yaml",
    "noise": "noise_profiles.yaml",
    "sources": "sources.yaml",
    "locations": "locations.yaml",
}


def resolve_config_dir(config_dir: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if config_dir is not None:
        candidates.append(Path(config_dir))
    elif env := os.environ.get("ORGGRAPH_CONFIG_DIR"):
        candidates.append(Path(env))
    else:
        package_dir = Path(__file__).resolve().parent
        candidates += [
            Path.cwd() / "config",
            package_dir.parents[1] / "config",
            package_dir / "_bundled_config",
        ]
    for candidate in candidates:
        if (candidate / CONFIG_FILES["dataset"]).is_file():
            return candidate
    tried = ", ".join(str(c) for c in candidates)
    raise ConfigError(f"configuration directory not found (tried: {tried})")


def load_raw_config(config_dir: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    directory = resolve_config_dir(config_dir)
    raw: dict[str, Any] = {}
    for section, filename in CONFIG_FILES.items():
        path = directory / filename
        if not path.is_file():
            raise ConfigError(f"missing configuration file: {path}")
        try:
            with path.open("r", encoding="utf-8") as handle:
                content = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
        if not isinstance(content, dict):
            raise ConfigError(f"{path} must contain a mapping at the top level")
        raw[section] = content
    return directory, raw


def apply_overrides(raw: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(raw)
    for dotted, value in overrides.items():
        parts = dotted.split(".")
        if len(parts) < 2 or parts[0] not in result:
            sections = ", ".join(CONFIG_FILES)
            raise ConfigError(f"invalid override '{dotted}': must start with one of {sections}")
        node: Any = result
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise ConfigError(f"invalid override '{dotted}': '{part}' does not exist")
            node = node[part]
        if not isinstance(node, dict):
            raise ConfigError(f"invalid override '{dotted}': parent is not a mapping")
        node[parts[-1]] = value
    return result


def parse_override_pairs(pairs: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ConfigError(f"override '{pair}' must look like section.key=value")
        key, value = pair.split("=", 1)
        overrides[key.strip()] = yaml.safe_load(value)
    return overrides


def _merge_archetype_defaults(raw_archetypes: dict[str, Any]) -> dict[str, Any]:
    defaults = raw_archetypes.get("defaults", {})
    merged = {
        name: {**defaults, **(spec or {})} for name, spec in (raw_archetypes.get("archetypes") or {}).items()
    }
    return {
        "division_name_patterns": raw_archetypes.get("division_name_patterns", []),
        "archetypes": merged,
    }


def build_config(raw: dict[str, Any]) -> OrgGraphConfig:
    prepared = dict(raw)
    prepared["archetypes"] = _merge_archetype_defaults(raw["archetypes"])
    try:
        return OrgGraphConfig.model_validate(prepared)
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            location = ".".join(str(part) for part in err["loc"]) or "<root>"
            lines.append(f"  - {location}: {err['msg']}")
        raise ConfigError("invalid configuration:\n" + "\n".join(lines)) from None


def load_config(
    config_dir: str | Path | None = None, overrides: dict[str, Any] | None = None
) -> OrgGraphConfig:
    _, raw = load_raw_config(config_dir)
    if overrides:
        raw = apply_overrides(raw, overrides)
    return build_config(raw)


def _cross_reference_errors(cfg: OrgGraphConfig) -> list[str]:
    checks = (
        _check_company_sizes,
        _check_industries,
        _check_departments,
        _check_job_families,
        _check_titles,
        _check_archetypes,
        _check_noise,
        _check_sources,
        _check_locations,
        _check_dataset_defaults,
    )
    return [error for check in checks for error in check(cfg)]


def _check_company_sizes(cfg: OrgGraphConfig) -> list[str]:
    segments = cfg.company_sizes.segments
    if tuple(segments) != SIZE_SEGMENTS:
        return [f"company_sizes.segments must be exactly {list(SIZE_SEGMENTS)} in order"]
    errors: list[str] = []
    previous_max = 0
    for key, seg in segments.items():
        if seg.min > seg.max:
            errors.append(f"company_sizes.{key}: min > max")
        if seg.min != previous_max + 1 and previous_max:
            errors.append(f"company_sizes.{key}: segments must be contiguous")
        previous_max = seg.max
    return errors


def _check_industries(cfg: OrgGraphConfig) -> list[str]:
    errors: list[str] = []
    departments = cfg.departments.departments
    exec_roles = cfg.titles.executive_roles
    regions = tuple(cfg.locations.regions)
    for key, industry in cfg.industries.industries.items():
        for dept_name in industry.departments:
            if dept_name not in departments:
                errors.append(f"industries.{key}: unknown department '{dept_name}'")
        for dept_key, role_key in industry.executive_overrides.items():
            if dept_key not in departments or role_key not in exec_roles:
                errors.append(f"industries.{key}.executive_overrides: bad entry '{dept_key}: {role_key}'")
        errors += _unknown_keys(f"industries.{key}.archetype_weights", industry.archetype_weights, ARCHETYPES)
        errors += _unknown_keys(f"industries.{key}.size_weights", industry.size_weights, SIZE_SEGMENTS)
        errors += _unknown_keys(f"industries.{key}.region_weights", industry.region_weights, regions)
    return errors


def _check_departments(cfg: OrgGraphConfig) -> list[str]:
    errors: list[str] = []
    families = cfg.job_families.families
    departments = cfg.departments.departments
    exec_roles = cfg.titles.executive_roles
    sub_keys: set[str] = set()
    for key, dept in departments.items():
        for fam in dept.families:
            if fam not in families:
                errors.append(f"departments.{key}: unknown family '{fam}'")
        if dept.management_family and dept.management_family not in families:
            errors.append(f"departments.{key}: unknown management_family")
        if key != "executive_office" and not families.get(dept.primary_family, None):
            errors.append(f"departments.{key}: primary family missing")
        elif key != "executive_office" and not families[dept.primary_family].management:
            errors.append(f"departments.{key}: management family must have a management ladder")
        if dept.executive and dept.executive not in exec_roles:
            errors.append(f"departments.{key}: unknown executive '{dept.executive}'")
        for sub in dept.subdepartments:
            if sub.key in sub_keys or sub.key in departments:
                errors.append(f"departments.{key}: duplicate subdepartment key '{sub.key}'")
            sub_keys.add(sub.key)
            for fam in sub.families or {}:
                if fam not in families:
                    errors.append(f"departments.{key}.{sub.key}: unknown family '{fam}'")
    if "executive_office" not in departments:
        errors.append("departments: 'executive_office' is required")
    return errors


def _check_job_families(cfg: OrgGraphConfig) -> list[str]:
    errors: list[str] = []
    industries = cfg.industries.industries
    for key, family_cfg in cfg.job_families.families.items():
        for level in family_cfg.ic_levels:
            if level not in IC_LEVELS:
                errors.append(f"job_families.{key}: invalid ic level '{level}'")
        for level in family_cfg.legacy_titles:
            if level not in SENIORITY_ORDER:
                errors.append(f"job_families.{key}.legacy_titles: invalid level '{level}'")
        for ind in family_cfg.industries or []:
            if ind not in industries:
                errors.append(f"job_families.{key}: unknown industry '{ind}'")
    return errors


def _check_titles(cfg: OrgGraphConfig) -> list[str]:
    errors: list[str] = []
    titles = cfg.titles
    if tuple(level.key for level in titles.seniority_levels) != SENIORITY_ORDER:
        errors.append(f"title_taxonomy.seniority_levels must be {list(SENIORITY_ORDER)} in order")
    for level in (*IC_LEVELS, *MANAGEMENT_LEVELS):
        if level not in titles.ladder_patterns:
            errors.append(f"title_taxonomy.ladder_patterns: missing level '{level}'")
    for fam, levels in titles.overrides.items():
        if fam not in cfg.job_families.families:
            errors.append(f"title_taxonomy.overrides: unknown family '{fam}'")
        for level in levels:
            if level not in SENIORITY_ORDER:
                errors.append(f"title_taxonomy.overrides.{fam}: invalid level '{level}'")
    for key, role in titles.executive_roles.items():
        if role.seniority not in SENIORITY_ORDER:
            errors.append(f"title_taxonomy.executive_roles.{key}: invalid seniority")
    if "ceo" not in titles.executive_roles:
        errors.append("title_taxonomy.executive_roles: 'ceo' is required")
    return errors


def _check_archetypes(cfg: OrgGraphConfig) -> list[str]:
    errors: list[str] = []
    archetypes = cfg.archetypes.archetypes
    departments = cfg.departments.departments
    if set(archetypes) != set(ARCHETYPES):
        errors.append(f"org_archetypes.archetypes must define exactly {list(ARCHETYPES)}")
    for key, arch in archetypes.items():
        for level in arch.levels:
            if level not in MANAGEMENT_LEVELS:
                errors.append(f"org_archetypes.{key}: invalid level '{level}'")
            if level not in arch.level_min_headcount or level not in arch.span_of_control:
                errors.append(f"org_archetypes.{key}: level '{level}' needs min headcount and span")
        for layer in arch.segmentation:
            if layer.head_role not in cfg.titles.executive_roles:
                errors.append(f"org_archetypes.{key}: unknown head_role '{layer.head_role}'")
        for dept_name in (*arch.secondary_member_departments, *arch.secondary_manager_departments):
            if dept_name not in departments:
                errors.append(f"org_archetypes.{key}: unknown department '{dept_name}'")
        errors += _unknown_keys(f"org_archetypes.{key}.size_weights", arch.size_weights, SIZE_SEGMENTS)
    return errors


def _check_noise(cfg: OrgGraphConfig) -> list[str]:
    noise = cfg.noise
    errors = [
        f"noise_profiles: required profile '{name}' missing"
        for name in REQUIRED_NOISE_PROFILES
        if name not in noise.profiles
    ]
    errors += _unknown_keys("noise.title_noise_weights", noise.title_noise_weights, TITLE_NOISE_OPERATIONS)
    errors += _unknown_keys(
        "noise.department_noise_weights", noise.department_noise_weights, DEPARTMENT_NOISE_OPERATIONS
    )
    errors += _unknown_keys(
        "noise.location_noise_weights", noise.location_noise_weights, LOCATION_NOISE_OPERATIONS
    )
    errors += [
        f"noise.generic_titles: tier '{tier}' missing"
        for tier in GENERIC_TITLE_TIERS
        if not noise.generic_titles.get(tier)
    ]
    return errors


def _check_sources(cfg: OrgGraphConfig) -> list[str]:
    errors: list[str] = []
    sources = cfg.sources
    if set(sources.sources) != set(SOURCES):
        errors.append(f"sources.sources must define exactly {list(SOURCES)}")
    if sources.fallback_source not in sources.sources:
        errors.append("sources.fallback_source must be a defined source")
    errors += _unknown_keys("sources.departed_source_coverage", sources.departed_source_coverage, SOURCES)
    return errors


def _check_locations(cfg: OrgGraphConfig) -> list[str]:
    regions = cfg.locations.regions
    cities = cfg.locations.cities
    errors = [
        f"locations: city '{city.name}' has unknown region '{city.region}'"
        for city in cities
        if city.region not in regions
    ]
    errors += [
        f"locations: region '{region}' has no cities"
        for region in regions
        if not any(c.region == region for c in cities)
    ]
    return errors


def _check_dataset_defaults(cfg: OrgGraphConfig) -> list[str]:
    errors: list[str] = []
    ds = cfg.dataset
    for profile in (ds.noise_profile, ds.challenge_noise_profile):
        if profile not in cfg.noise.profiles:
            errors.append(f"dataset_defaults: unknown noise profile '{profile}'")
    if set(ds.splits.fractions) != set(SPLITS):
        errors.append(f"dataset_defaults.splits.fractions must define exactly {list(SPLITS)}")
    elif abs(sum(ds.splits.fractions.values()) - 1.0) > 1e-6:
        errors.append("dataset_defaults.splits.fractions must sum to 1")
    for ind in ds.splits.holdout_industries:
        if ind not in cfg.industries.industries:
            errors.append(f"dataset_defaults.splits.holdout_industries: unknown industry '{ind}'")
    errors += _unknown_keys("workforce.ic_seniority_mix", ds.workforce.ic_seniority_mix, IC_LEVELS)
    errors += _unknown_keys("workforce.leader_direct_ic_mix", ds.workforce.leader_direct_ic_mix, IC_LEVELS)
    errors += _unknown_keys(
        "workforce.employment_type_mix",
        ds.workforce.employment_type_mix,
        ("full_time", "contractor", "part_time"),
    )
    return errors


def _unknown_keys(where: str, mapping: dict[str, Any], allowed: tuple[str, ...]) -> list[str]:
    return [f"{where}: unknown key '{key}'" for key in mapping if key not in allowed]
