# Enumerations shared by the schemas
from __future__ import annotations

from enum import StrEnum


class SeniorityLevel(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    IC = "ic"
    SENIOR_IC = "senior_ic"
    STAFF = "staff"
    PRINCIPAL = "principal"
    MANAGER = "manager"
    SENIOR_MANAGER = "senior_manager"
    DIRECTOR = "director"
    SENIOR_DIRECTOR = "senior_director"
    VP = "vp"
    SVP = "svp"
    EXECUTIVE = "executive"
    C_LEVEL = "c_level"


class SizeSegment(StrEnum):
    SMALL = "small"
    MID_SMALL = "mid_small"
    MID_MARKET = "mid_market"
    LARGE = "large"
    ENTERPRISE = "enterprise"


class OrgArchetype(StrEnum):
    FUNCTIONAL = "functional"
    PRODUCT_BASED = "product_based"
    REGIONAL = "regional"
    BUSINESS_UNIT = "business_unit"
    FLAT_STARTUP = "flat_startup"
    ENTERPRISE = "enterprise"
    MATRIX = "matrix"


class DepartmentType(StrEnum):
    EXECUTIVE = "executive"
    FUNCTION = "function"
    SUB_FUNCTION = "sub_function"
    BUSINESS_UNIT = "business_unit"
    DIVISION = "division"
    REGION = "region"
    PRODUCT_LINE = "product_line"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    CONTRACTOR = "contractor"
    INTERN = "intern"
    PART_TIME = "part_time"


class EmploymentStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    FORMER = "former"
    UNKNOWN = "unknown"


class Source(StrEnum):
    HR_EXPORT = "hr_export"
    COMPANY_DIRECTORY = "company_directory"
    PUBLIC_PROFILE = "public_profile"
    INTERNAL_DIRECTORY = "internal_directory"
    HISTORICAL_SNAPSHOT = "historical_snapshot"


class RelationshipType(StrEnum):
    PRIMARY = "primary"
    ROOT = "root"
    SECONDARY = "secondary"


class Split(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    CHALLENGE = "challenge"
