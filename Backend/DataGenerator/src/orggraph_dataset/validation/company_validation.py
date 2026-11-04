# Company-level constraints
from __future__ import annotations

from orggraph_dataset.schemas import CompanyRecords
from orggraph_dataset.validation.report import GlobalIdRegistry, ValidationContext, ValidationReport


def validate_company(
    records: CompanyRecords,
    ctx: ValidationContext,
    report: ValidationReport,
    registry: GlobalIdRegistry,
) -> None:
    company = records.company
    cid = company.company_id
    report.check("company")

    if cid in registry.company_ids:
        report.error("company.duplicate_id", "company_id appears more than once", cid)
    registry.company_ids.add(cid)

    if company.industry not in ctx.industry_names:
        report.error("company.invalid_industry", f"unknown industry '{company.industry}'", cid)

    if company.employee_count < ctx.min_employees_per_company:
        report.error(
            "company.too_few_employees",
            f"employee_count {company.employee_count} < minimum {ctx.min_employees_per_company}",
            cid,
        )
    if company.employee_count != len(records.employees):
        report.error(
            "company.employee_count_mismatch",
            f"employee_count {company.employee_count} != {len(records.employees)} canonical employees",
            cid,
        )
    low, high = ctx.segment_bounds[company.company_size_segment.value]
    if not low <= company.employee_count <= high:
        report.error(
            "company.invalid_size_segment",
            f"{company.employee_count} employees is outside segment "
            f"{company.company_size_segment.value} [{low}, {high}]",
            cid,
        )
    if len(set(company.operating_regions)) != len(company.operating_regions):
        report.error("company.duplicate_region", "operating_regions contains duplicates", cid)


def validate_company_count(company_count: int, minimum: int | None, report: ValidationReport) -> None:
    report.check("dataset.company_count")
    if minimum is not None and company_count < minimum:
        report.error("dataset.too_few_companies", f"{company_count} companies < required {minimum}")
