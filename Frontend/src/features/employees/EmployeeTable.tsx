// Filterable, paginated table of a company's employees
"use client";

import { useEffect, useState } from "react";

import { Badge, Card, ConfidenceBadge, EmptyState, ErrorState, Field, inputClass, Pagination, Spinner, TextLink } from "@/components/ui";
import { api, type EmployeeQuery } from "@/lib/api/endpoints";
import { humanize } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

const SENIORITY = ["c_level", "executive", "svp", "vp", "senior_director", "director", "senior_manager", "manager", "principal", "staff", "senior_ic", "ic", "junior", "intern"];

export function EmployeeTable({ datasetId, companyId }: { datasetId: string; companyId: string }) {
  const [filters, setFilters] = useState<EmployeeQuery>({});
  const [text, setText] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    const timer = setTimeout(() => {
      setFilters((f) => ({ ...f, q: text || undefined }));
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [text]);
  const rows = useAsync(() => api.employees(datasetId, companyId, { ...filters, page, page_size: 50 }), [datasetId, companyId, filters, page]);
  const set = (patch: Partial<EmployeeQuery>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };

  return (
    <Card title="Employees (inferred profiles)">
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Search">
          <input className={inputClass} placeholder="Name, title or ID" value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Field label="Seniority">
          <select className={inputClass} value={filters.seniority ?? ""} onChange={(e) => set({ seniority: e.target.value || undefined })}>
            <option value="">All</option>
            {SENIORITY.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Manager">
          <select
            className={inputClass}
            value={filters.resolved === undefined ? "" : String(filters.resolved)}
            onChange={(e) => set({ resolved: e.target.value === "" ? undefined : e.target.value === "true" })}
          >
            <option value="">Any</option>
            <option value="true">Resolved</option>
            <option value="false">Unresolved</option>
          </select>
        </Field>
        <Field label="Department">
          <input className={inputClass} placeholder="e.g. engineering" value={filters.department ?? ""} onChange={(e) => set({ department: e.target.value || undefined })} />
        </Field>
      </div>
      {rows.error && <ErrorState error={rows.error} onRetry={rows.reload} />}
      {rows.loading && !rows.data && <Spinner />}
      {rows.data && rows.data.items.length === 0 && <EmptyState>No employees match.</EmptyState>}
      {rows.data && rows.data.items.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2">Name</th>
                  <th className="py-2">Observed / inferred title</th>
                  <th className="py-2">Seniority</th>
                  <th className="py-2">Department</th>
                  <th className="py-2">Manager</th>
                  <th className="py-2 text-right">Reports</th>
                </tr>
              </thead>
              <tbody>
                {rows.data.items.map((e) => (
                  <tr key={e.employee_id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="py-2">
                      <TextLink href={`/companies/${companyId}/employees/${e.employee_id}`}>{e.full_name}</TextLink>
                      {e.departed && (
                        <span className="ml-2">
                          <Badge tone="red">departed?</Badge>
                        </span>
                      )}
                    </td>
                    <td className="py-2">
                      <div>{e.title ?? "—"}</div>
                      {e.inferred_title && e.inferred_title !== e.title && <div className="text-xs text-slate-500">→ {e.inferred_title}</div>}
                    </td>
                    <td className="py-2">{humanize(e.seniority)}</td>
                    <td className="py-2">{e.department ?? "—"}</td>
                    <td className="py-2">
                      {e.predicted_manager_id ? (
                        <span className="flex items-center gap-2">
                          <TextLink href={`/companies/${companyId}/employees/${e.predicted_manager_id}`}>view</TextLink>
                          <ConfidenceBadge confidence={e.confidence} />
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">abstained</span>
                      )}
                    </td>
                    <td className="py-2 text-right tabular-nums">{e.direct_reports}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={50} total={rows.data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}
