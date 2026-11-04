# Observation constraints: references, missing-field representation, timestamps, labels
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from orggraph_dataset.constants import NULLABLE_OBSERVATION_FIELDS
from orggraph_dataset.schemas import CompanyRecords
from orggraph_dataset.validation.report import GlobalIdRegistry, ValidationContext, ValidationReport


def validate_observations(
    records: CompanyRecords,
    ctx: ValidationContext,
    report: ValidationReport,
    registry: GlobalIdRegistry,
) -> None:
    cid = records.company.company_id
    current = {e.employee_id for e in records.employees}
    departed = {d.employee_id for d in records.departed_employees}
    known = current | departed
    latest = datetime.combine(ctx.reference_date, time(), tzinfo=UTC) + timedelta(days=1)
    earliest = latest - timedelta(days=365 * 10)

    seen: set[str] = set()
    observed_employees: set[str] = set()
    for obs in records.observations:
        report.check("observation")
        oid = obs.observation_id
        if oid in seen or oid in registry.observation_ids:
            report.error("observation.duplicate_id", "observation_id is not unique", cid, oid)
        seen.add(oid)
        if not oid.startswith("obs_"):
            report.error("observation.invalid_id", "observation_id must start with 'obs_'", cid, oid)
        if obs.company_id != cid:
            report.error("observation.wrong_company", f"company_id {obs.company_id} != {cid}", cid, oid)
        if obs.employee_id not in known:
            report.error("observation.unknown_employee", f"employee {obs.employee_id} unknown", cid, oid)
        observed_employees.add(obs.employee_id)

        nulls = [f for f in NULLABLE_OBSERVATION_FIELDS if getattr(obs, f) is None]
        if len(obs.missing_fields) != len(set(obs.missing_fields)):
            report.error("observation.duplicate_missing_field", "missing_fields has duplicates", cid, oid)
        if set(obs.missing_fields) != set(nulls):
            report.error(
                "observation.missing_fields_mismatch",
                f"missing_fields {sorted(obs.missing_fields)} != null fields {sorted(nulls)}",
                cid,
                oid,
            )
        if obs.observed_at is not None:
            if obs.observed_at.tzinfo is None:
                report.error("observation.naive_timestamp", "observed_at must be timezone-aware", cid, oid)
            elif not earliest <= obs.observed_at <= latest:
                report.error(
                    "observation.timestamp_out_of_range",
                    f"observed_at {obs.observed_at} out of range",
                    cid,
                    oid,
                )
        if obs.historical_manager_id is not None and obs.historical_manager_id not in current:
            report.error(
                "observation.unknown_historical_manager",
                "historical_manager_id is not a current employee",
                cid,
                oid,
            )
    registry.observation_ids.update(seen)

    unobserved = current - observed_employees
    if unobserved:
        report.error(
            "observation.unobserved_employee",
            f"{len(unobserved)} employees have no observation",
            cid,
        )

    labels = {lbl.observation_id: lbl for lbl in records.observation_labels}
    if len(labels) != len(records.observation_labels) or set(labels) != seen:
        report.error("observation.label_mismatch", "observation labels are not 1:1 with observations", cid)
    for obs in records.observations:
        label = labels.get(obs.observation_id)
        if label is None:
            continue
        if label.employee_id != obs.employee_id:
            report.error(
                "observation.label_employee_mismatch",
                "label refers to another employee",
                cid,
                obs.observation_id,
            )
        if obs.source is not None and obs.source != label.true_source:
            report.error(
                "observation.label_source_mismatch",
                "observed source differs from true source",
                cid,
                obs.observation_id,
            )
        if label.is_departed_employee != (obs.employee_id in departed):
            report.error(
                "observation.label_departed_mismatch",
                "departed flag is wrong",
                cid,
                obs.observation_id,
            )
