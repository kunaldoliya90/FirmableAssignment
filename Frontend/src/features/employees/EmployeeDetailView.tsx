// Employee profile, predicted manager, candidates, evidence and observations
"use client";

import Link from "next/link";

import { Badge, Card, ConfidenceBadge, EmptyState, ErrorState, PageHeader, Spinner, StatTile, TextLink } from "@/components/ui";
import { useDataset } from "@/features/datasets/DatasetContext";
import { api } from "@/lib/api/endpoints";
import type { EmployeeRef, Evidence } from "@/lib/api/types";
import { formatDate, formatPercent, humanize } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

function PersonLink({ companyId, person }: { companyId: string; person: EmployeeRef }) {
  return (
    <span>
      <TextLink href={`/companies/${companyId}/employees/${person.employee_id}`}>{person.full_name}</TextLink>
      <span className="text-xs text-slate-500"> · {person.title ?? "unknown title"}</span>
    </span>
  );
}

const REASON_TEXT: Record<string, string> = {
  confident: "Manager predicted with enough confidence.",
  below_threshold: "Best candidate was not confident enough, so the engine abstained.",
  departed: "Looks like a former employee (stale sources only / marked former), so no manager is assigned.",
  root: "Identified as the top of the organization.",
  no_candidates: "No plausible higher-ranked colleague was found.",
  cycle_broken: "Removed to keep the predicted graph acyclic.",
};

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  const signals = evidence.find((e) => e.type === "signals") as { matched?: string[] } | undefined;
  const candidates = evidence.find((e) => e.type === "candidates") as { considered?: number; abstain_probability?: number } | undefined;
  return (
    <div className="space-y-3 text-sm">
      {signals?.matched && signals.matched.length > 0 && (
        <div>
          <div className="text-xs font-semibold uppercase text-slate-500">Signals supporting the chosen manager</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {signals.matched.map((s) => (
              <Badge key={s} tone={s.includes("conflict") || s.includes("wrong") || s.includes("not_manager") ? "red" : "blue"}>
                {humanize(s)}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {candidates && (
        <div className="text-xs text-slate-500">
          {candidates.considered} candidates scored · probability that none of them is right: {formatPercent(candidates.abstain_probability ?? 0)}
        </div>
      )}
    </div>
  );
}

export function EmployeeDetailView({ companyId, employeeId }: { companyId: string; employeeId: string }) {
  const { datasetId } = useDataset();
  const detail = useAsync(datasetId ? () => api.employee(datasetId, companyId, employeeId) : null, [datasetId, companyId, employeeId]);

  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return <Spinner label="Loading employee (runs company inference if needed)…" />;
  const e = detail.data;

  return (
    <>
      <PageHeader
        title={e.full_name}
        subtitle={
          <>
            {e.title ?? "Unknown title"}
            {e.inferred_title && e.inferred_title !== e.title && <> → <strong>{e.inferred_title}</strong></>} ·{" "}
            <Link className="text-brand-700 hover:underline" href={`/companies/${companyId}`}>
              {companyId}
            </Link>
          </>
        }
        actions={
          <Link className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50" href={`/companies/${companyId}?focus=${employeeId}`}>
            Show in org chart
          </Link>
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatTile label="Seniority" value={humanize(e.seniority)} hint={`confidence ${formatPercent(e.seniority_confidence, 0)}`} />
        <StatTile label="Department" value={e.department ?? "—"} hint={`confidence ${formatPercent(e.department_confidence, 0)}`} />
        <StatTile label="Job family" value={humanize(e.job_family)} />
        <StatTile label="Region" value={humanize(e.region)} hint={e.city ?? undefined} />
        <StatTile label="Employment" value={humanize(e.employment_type)} hint={e.departed ? `likely departed (${formatPercent(e.departed_confidence, 0)})` : undefined} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Predicted manager" className="xl:col-span-1">
          {e.manager ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <PersonLink companyId={companyId} person={e.manager} />
                <ConfidenceBadge confidence={e.confidence} />
              </div>
            </div>
          ) : (
            <EmptyState>No manager assigned.</EmptyState>
          )}
          <p className="mt-3 text-xs text-slate-500">{REASON_TEXT[e.decision_reason] ?? humanize(e.decision_reason)}</p>
          {e.candidates.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Top candidates</div>
              <ul className="mt-1 space-y-1 text-sm">
                {e.candidates.map((c) => (
                  <li key={c.employee_id} className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      <TextLink href={`/companies/${companyId}/employees/${c.employee_id}`}>{c.full_name ?? c.employee_id}</TextLink>
                      <span className="text-xs text-slate-500"> · {c.title ?? "—"}</span>
                    </span>
                    <span className="tabular-nums text-xs text-slate-600">{formatPercent(c.probability, 0)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4">
            <EvidenceList evidence={e.evidence} />
          </div>
        </Card>

        <Card title="Chain of command">
          {e.chain_of_command.length === 0 ? (
            <EmptyState>Top of the resolved chain.</EmptyState>
          ) : (
            <ol className="space-y-2 text-sm">
              {e.chain_of_command.map((p, i) => (
                <li key={p.employee_id} style={{ paddingLeft: `${i * 10}px` }}>
                  <PersonLink companyId={companyId} person={p} />
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title={`Direct reports (${e.reports.length})`}>
          {e.reports.length === 0 ? (
            <EmptyState>No confident direct reports.</EmptyState>
          ) : (
            <ul className="max-h-80 space-y-2 overflow-y-auto text-sm">
              {e.reports.map((p) => (
                <li key={p.employee_id}>
                  <PersonLink companyId={companyId} person={p} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-6">
        <Card title={`Observations (${e.observations.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2">Source</th>
                  <th className="py-2">Title</th>
                  <th className="py-2">Department</th>
                  <th className="py-2">Location</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Observed</th>
                  <th className="py-2">Missing</th>
                </tr>
              </thead>
              <tbody>
                {e.observations.map((o) => (
                  <tr key={o.observation_id} className="border-t border-slate-100 align-top">
                    <td className="py-2">{humanize(o.source)}</td>
                    <td className="py-2">{o.observed_title ?? "—"}</td>
                    <td className="py-2">{o.observed_department ?? "—"}</td>
                    <td className="py-2">{o.observed_location ?? "—"}</td>
                    <td className="py-2">{o.employment_status}</td>
                    <td className="py-2 text-xs">{formatDate(o.observed_at)}</td>
                    <td className="py-2 text-xs text-slate-500">{o.missing_fields.map(humanize).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
