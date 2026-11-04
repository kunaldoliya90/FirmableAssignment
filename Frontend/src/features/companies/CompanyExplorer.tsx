// Company list with search, filters, sorting and pagination
"use client";

import { useEffect, useState } from "react";

import { Badge, Card, EmptyState, ErrorState, Field, inputClass, Pagination, Spinner, TextLink } from "@/components/ui";
import { useDataset } from "@/features/datasets/DatasetContext";
import { api, type CompanyQuery } from "@/lib/api/endpoints";
import { formatNumber, humanize } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

const PAGE_SIZE = 25;

export function CompanyExplorer() {
  const { datasetId } = useDataset();
  const [query, setQuery] = useState<CompanyQuery>({ sort: "company_name" });
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery((q) => ({ ...q, q: search || undefined }));
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const facets = useAsync(datasetId ? () => api.facets(datasetId) : null, [datasetId]);
  const companies = useAsync(
    datasetId ? () => api.companies(datasetId, { ...query, page, page_size: PAGE_SIZE }) : null,
    [datasetId, query, page],
  );

  const set = (patch: Partial<CompanyQuery>) => {
    setQuery((q) => ({ ...q, ...patch }));
    setPage(1);
  };

  return (
    <Card>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Field label="Search">
          <input className={inputClass} placeholder="Name or company ID" value={search} onChange={(e) => setSearch(e.target.value)} />
        </Field>
        <Field label="Split">
          <select className={inputClass} value={query.split ?? ""} onChange={(e) => set({ split: e.target.value || undefined })}>
            <option value="">All</option>
            {Object.keys(facets.data?.split ?? {}).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field label="Industry">
          <select className={inputClass} value={query.industry ?? ""} onChange={(e) => set({ industry: e.target.value || undefined })}>
            <option value="">All</option>
            {Object.keys(facets.data?.industry ?? {}).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field label="Size">
          <select className={inputClass} value={query.size_segment ?? ""} onChange={(e) => set({ size_segment: e.target.value || undefined })}>
            <option value="">All</option>
            {Object.keys(facets.data?.company_size_segment ?? {}).map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Sort">
          <select
            className={inputClass}
            value={`${query.sort}:${query.descending ? "desc" : "asc"}`}
            onChange={(e) => {
              const [sort, dir] = e.target.value.split(":");
              set({ sort: sort as CompanyQuery["sort"], descending: dir === "desc" });
            }}
          >
            <option value="company_name:asc">Name</option>
            <option value="employee_count:desc">Largest first</option>
            <option value="employee_count:asc">Smallest first</option>
            <option value="industry:asc">Industry</option>
          </select>
        </Field>
      </div>

      {companies.error && <ErrorState error={companies.error} onRetry={companies.reload} />}
      {companies.loading && !companies.data && <Spinner />}
      {companies.data && companies.data.items.length === 0 && <EmptyState>No companies match these filters.</EmptyState>}
      {companies.data && companies.data.items.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2">Company</th>
                  <th className="py-2">Industry</th>
                  <th className="py-2">Size</th>
                  <th className="py-2 text-right">Employees</th>
                  <th className="py-2">Headquarters</th>
                  <th className="py-2">Split</th>
                  <th className="py-2">Inference</th>
                </tr>
              </thead>
              <tbody>
                {companies.data.items.map((c) => (
                  <tr key={c.company_id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="py-2">
                      <TextLink href={`/companies/${c.company_id}`}>{c.company_name}</TextLink>
                      <div className="text-xs text-slate-400">{c.company_id}</div>
                    </td>
                    <td className="py-2">{c.industry}</td>
                    <td className="py-2">{humanize(c.company_size_segment)}</td>
                    <td className="py-2 text-right tabular-nums">{formatNumber(c.employee_count)}</td>
                    <td className="py-2">{c.headquarters}</td>
                    <td className="py-2">
                      <Badge tone={c.split === "challenge" ? "amber" : "neutral"}>{c.split}</Badge>
                    </td>
                    <td className="py-2">{c.inferred ? <Badge tone="green">cached</Badge> : <span className="text-xs text-slate-400">on open</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={companies.data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}
