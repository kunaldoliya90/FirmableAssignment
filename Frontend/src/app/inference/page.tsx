// Inference page: single-company runs and split-level jobs
"use client";

import { useState } from "react";

import { Button, Card, EmptyState, ErrorState, Field, inputClass, PageHeader, Spinner, StatTile, TextLink } from "@/components/ui";
import { useDataset } from "@/features/datasets/DatasetContext";
import { SplitSelector } from "@/features/inference/SplitSelector";
import { JobStatus } from "@/features/jobs/JobsPanel";
import { api } from "@/lib/api/endpoints";
import type { CompanyInferenceResult } from "@/lib/api/types";
import { formatNumber, formatPercent, humanize } from "@/lib/format";
import { useAsync, useJob } from "@/lib/hooks";

function CompanyInference({ datasetId }: { datasetId: string }) {
  const [companyId, setCompanyId] = useState("");
  const [result, setResult] = useState<CompanyInferenceResult>();
  const [error, setError] = useState<Error>();
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    setError(undefined);
    try {
      setResult(await api.inferCompany(datasetId, companyId.trim(), true));
    } catch (err) {
      setError(err as Error);
    } finally {
      setRunning(false);
    }
  };

  return (
    <Card title="Infer one company">
      <div className="flex items-end gap-3">
        <Field label="Company ID">
          <input className={inputClass} placeholder="company_00001" value={companyId} onChange={(e) => setCompanyId(e.target.value)} />
        </Field>
        <Button onClick={() => void run()} disabled={running || companyId.trim().length === 0}>
          {running ? "Inferring…" : "Run inference"}
        </Button>
      </div>
      {error && (
        <div className="mt-3">
          <ErrorState error={error} />
        </div>
      )}
      {running && <Spinner label="Normalizing titles, building profiles, scoring candidates…" />}
      {result && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Employees" value={formatNumber(result.employees)} />
            <StatTile label="Confident edges" value={formatNumber(result.predicted_edges)} hint={formatPercent(result.predicted_edges / result.employees)} />
            <StatTile label="Abstentions" value={formatNumber(result.abstentions)} />
            <StatTile label="Departed detected" value={formatNumber(result.departed_detected)} />
          </div>
          <div className="text-xs text-slate-500">
            {Object.entries(result.decision_reasons)
              .map(([k, v]) => `${humanize(k)}: ${formatNumber(v)}`)
              .join(" · ")}{" "}
            · {result.elapsed_seconds}s
          </div>
          <TextLink href={`/companies/${result.company_id}`}>Open the org chart →</TextLink>
        </div>
      )}
    </Card>
  );
}

export default function InferencePage() {
  const { datasetId } = useDataset();
  const [splits, setSplits] = useState<string[]>(["test"]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<Error>();
  const runs = useAsync(datasetId ? () => api.inferenceRuns(datasetId) : null, [datasetId]);
  const job = useJob(jobId, () => runs.reload());

  const start = async () => {
    if (!datasetId) return;
    setError(undefined);
    try {
      setJobId((await api.runInference(datasetId, splits)).id);
    } catch (err) {
      setError(err as Error);
    }
  };

  return (
    <>
      <PageHeader
        title="Inference"
        subtitle="Infer reporting lines from observed records only: title normalization, profiles, candidate generation, scoring, graph optimization."
      />
      {!datasetId ? (
        <Spinner />
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          <CompanyInference datasetId={datasetId} />
          <Card title="Infer whole splits">
            <SplitSelector value={splits} onChange={setSplits} />
            <div className="mt-3">
              <Button onClick={() => void start()} disabled={splits.length === 0 || job?.status === "running" || job?.status === "queued"}>
                Run in background
              </Button>
            </div>
            {error && (
              <div className="mt-3">
                <ErrorState error={error} />
              </div>
            )}
            {job && (
              <div className="mt-4 rounded-lg bg-slate-50 p-3">
                <JobStatus job={job} />
              </div>
            )}
            <div className="mt-5 text-xs font-semibold uppercase text-slate-500">Stored predictions</div>
            {runs.error && <ErrorState error={runs.error} onRetry={runs.reload} />}
            {runs.data && runs.data.length === 0 && <EmptyState>No split predictions yet.</EmptyState>}
            {runs.data && runs.data.length > 0 && (
              <table className="mt-2 w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-1">Split</th>
                    <th className="py-1 text-right">Employees</th>
                    <th className="py-1 text-right">Edges</th>
                    <th className="py-1 text-right">Seconds</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.map((r) => (
                    <tr key={r.split} className="border-t border-slate-100">
                      <td className="py-1.5 font-medium">{r.split}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatNumber(r.summary.employees as number)}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatNumber(r.summary.predicted_edges as number)}</td>
                      <td className="py-1.5 text-right tabular-nums">{String(r.summary.elapsed_seconds ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
