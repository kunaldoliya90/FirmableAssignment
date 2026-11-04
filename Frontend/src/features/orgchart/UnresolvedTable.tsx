// Employees the engine abstained on, with reason and best candidate
"use client";

import { useState } from "react";

import { Badge, Card, EmptyState, ErrorState, Field, inputClass, Pagination, Spinner, TextLink } from "@/components/ui";
import { api } from "@/lib/api/endpoints";
import { formatPercent, humanize } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

const REASONS = ["below_threshold", "departed", "no_candidates", "cycle_broken"];

export function UnresolvedTable({ datasetId, companyId }: { datasetId: string; companyId: string }) {
  const [page, setPage] = useState(1);
  const [reason, setReason] = useState<string>("");
  const rows = useAsync(() => api.unresolved(datasetId, companyId, page, reason || undefined), [datasetId, companyId, page, reason]);

  return (
    <Card
      title="Unresolved employees"
      actions={
        <Field label="">
          <select
            aria-label="Reason"
            className={inputClass}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All reasons</option>
            {REASONS.map((r) => (
              <option key={r} value={r}>
                {humanize(r)}
              </option>
            ))}
          </select>
        </Field>
      }
    >
      <p className="mb-3 text-sm text-slate-500">
        The engine abstains instead of guessing when the evidence is weak: a wrong reporting line is worse than an unresolved one. The best
        tentative candidate is shown for review but is not part of the org chart.
      </p>
      {rows.error && <ErrorState error={rows.error} onRetry={rows.reload} />}
      {rows.loading && !rows.data && <Spinner />}
      {rows.data && rows.data.items.length === 0 && <EmptyState>Everyone was placed.</EmptyState>}
      {rows.data && rows.data.items.length > 0 && (
        <>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2">Employee</th>
                <th className="py-2">Inferred title</th>
                <th className="py-2">Department</th>
                <th className="py-2">Reason</th>
                <th className="py-2">Best tentative manager</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.items.map((u) => (
                <tr key={u.employee_id} className="border-t border-slate-100">
                  <td className="py-2">
                    <TextLink href={`/companies/${companyId}/employees/${u.employee_id}`}>{u.full_name}</TextLink>
                  </td>
                  <td className="py-2">{u.title ?? "—"}</td>
                  <td className="py-2">{u.department ? humanize(u.department) : "—"}</td>
                  <td className="py-2">
                    <Badge tone={u.reason === "departed" ? "red" : "amber"}>{humanize(u.reason)}</Badge>
                  </td>
                  <td className="py-2">
                    {u.best_candidate_id ? (
                      <>
                        <TextLink href={`/companies/${companyId}/employees/${u.best_candidate_id}`}>{u.best_candidate_name}</TextLink>{" "}
                        <span className="text-xs text-slate-500">p={formatPercent(u.best_probability, 0)}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={page} pageSize={rows.data.page_size} total={rows.data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}
