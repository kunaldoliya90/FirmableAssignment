// Employee search across every company in the dataset
"use client";

import { useEffect, useState } from "react";

import { Badge, Card, EmptyState, ErrorState, inputClass, PageHeader, Pagination, Spinner, TextLink } from "@/components/ui";
import { useDataset } from "@/features/datasets/DatasetContext";
import { api } from "@/lib/api/endpoints";
import { useAsync } from "@/lib/hooks";

export default function SearchPage() {
  const { datasetId } = useDataset();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(text.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [text]);
  const results = useAsync(datasetId && query.length >= 2 ? () => api.search(datasetId, query, page) : null, [datasetId, query, page]);

  return (
    <>
      <PageHeader title="Employee search" subtitle="Find people by name or employee ID across every company in the dataset." />
      <Card>
        <input
          className={`${inputClass} w-full`}
          placeholder="Type at least 2 characters, e.g. a surname"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Search employees"
        />
        <div className="mt-4">
          {query.length < 2 && <EmptyState>Start typing to search.</EmptyState>}
          {results.error && <ErrorState error={results.error} onRetry={results.reload} />}
          {results.loading && <Spinner />}
          {results.data && results.data.items.length === 0 && <EmptyState>No employees match “{query}”.</EmptyState>}
          {results.data && results.data.items.length > 0 && (
            <>
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-2">Name</th>
                    <th className="py-2">Employee ID</th>
                    <th className="py-2">Company</th>
                    <th className="py-2">Split</th>
                  </tr>
                </thead>
                <tbody>
                  {results.data.items.map((hit) => (
                    <tr key={hit.employee_id} className="border-t border-slate-100">
                      <td className="py-2">
                        <TextLink href={`/companies/${hit.company_id}/employees/${hit.employee_id}`}>{hit.full_name}</TextLink>
                      </td>
                      <td className="py-2 text-xs text-slate-500">{hit.employee_id}</td>
                      <td className="py-2">
                        <TextLink href={`/companies/${hit.company_id}`}>{hit.company_name}</TextLink>
                      </td>
                      <td className="py-2">
                        <Badge>{hit.split}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination page={page} pageSize={results.data.page_size} total={results.data.total} onPage={setPage} />
            </>
          )}
        </div>
      </Card>
    </>
  );
}
