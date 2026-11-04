// Run evaluations and browse stored reports
"use client";

import { useEffect, useState } from "react";

import { Button, Card, cx, EmptyState, ErrorState, inputClass, Spinner } from "@/components/ui";
import { useDataset } from "@/features/datasets/DatasetContext";
import { SplitSelector } from "@/features/inference/SplitSelector";
import { JobStatus } from "@/features/jobs/JobsPanel";
import { api } from "@/lib/api/endpoints";
import type { BenchmarkReport } from "@/lib/api/types";
import { formatDate, formatDecimal, formatNumber, formatPercent, humanize } from "@/lib/format";
import { useAsync, useJob } from "@/lib/hooks";

import { MetricsGrid } from "./MetricsGrid";
import { ReliabilityChart } from "./ReliabilityChart";

function Breakdown({ report }: { report: BenchmarkReport }) {
  const dims = Object.keys(report.breakdowns);
  const [dim, setDim] = useState(dims.includes("noise_profile") ? "noise_profile" : (dims[0] ?? ""));
  const rows = Object.entries(report.breakdowns[dim] ?? {});
  return (
    <Card
      title="Breakdown"
      actions={
        <select aria-label="Breakdown dimension" className={inputClass} value={dim} onChange={(e) => setDim(e.target.value)}>
          {dims.map((d) => (
            <option key={d} value={d}>
              {humanize(d)}
            </option>
          ))}
        </select>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="py-2">{humanize(dim)}</th>
              <th className="py-2 text-right">Employees</th>
              <th className="py-2 text-right">Precision</th>
              <th className="py-2 text-right">Recall</th>
              <th className="py-2 text-right">F1</th>
              <th className="py-2 text-right">Coverage</th>
              <th className="py-2 text-right">Penalized</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([value, m]) => (
              <tr key={value} className="border-t border-slate-100">
                <td className="py-1.5 font-medium">{humanize(value)}</td>
                <td className="py-1.5 text-right tabular-nums">{formatNumber(m.counts.employees)}</td>
                <td className="py-1.5 text-right tabular-nums">{formatPercent(m.edge_precision)}</td>
                <td className="py-1.5 text-right tabular-nums">{formatPercent(m.edge_recall)}</td>
                <td className="py-1.5 text-right tabular-nums">{formatPercent(m.edge_f1)}</td>
                <td className="py-1.5 text-right tabular-nums">{formatPercent(m.coverage)}</td>
                <td className="py-1.5 text-right tabular-nums">{formatDecimal(m.penalized_score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ReportView({ report }: { report: BenchmarkReport }) {
  return (
    <div className="space-y-6">
      <MetricsGrid metrics={report.overall} />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Confidence calibration">
          <div className="flex flex-wrap items-start gap-6">
            <ReliabilityChart bins={report.calibration.reliability} />
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="text-xs uppercase text-slate-500">Expected calibration error</dt>
                <dd className="font-semibold">{formatDecimal(report.calibration.expected_calibration_error)}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-slate-500">Max calibration error</dt>
                <dd className="font-semibold">{formatDecimal(report.calibration.max_calibration_error)}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-slate-500">Brier score</dt>
                <dd className="font-semibold">{formatDecimal(report.calibration.brier_score)}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-slate-500">Answered predictions</dt>
                <dd className="font-semibold">{formatNumber(report.calibration.answered_predictions)}</dd>
              </div>
            </dl>
          </div>
        </Card>
        <Card title="Risk / coverage">
          <p className="mb-3 text-sm text-slate-500">Precision if only answers at or above each confidence were kept.</p>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1">Confidence ≥</th>
                <th className="py-1 text-right">Answered</th>
                <th className="py-1 text-right">Precision</th>
                <th className="py-1 text-right">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {report.risk_coverage.map((row) => (
                <tr key={row.threshold} className="border-t border-slate-100">
                  <td className="py-1.5">{row.threshold}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatNumber(row.answered)}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatPercent(row.precision)}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatPercent(row.coverage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <Breakdown report={report} />
    </div>
  );
}

export function EvaluationDashboard() {
  const { datasetId } = useDataset();
  const [splits, setSplits] = useState<string[]>(["test"]);
  const [rerun, setRerun] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<Error>();
  const list = useAsync(datasetId ? () => api.evaluations(datasetId) : null, [datasetId]);
  const job = useJob(jobId, (finished) => {
    list.reload();
    const id = finished.result?.evaluation_id;
    if (typeof id === "string") setSelected(id);
  });
  useEffect(() => {
    if (!selected && list.data?.[0]) setSelected(list.data[0].evaluation_id);
  }, [list.data, selected]);
  const report = useAsync(datasetId && selected ? () => api.evaluation(datasetId, selected) : null, [datasetId, selected]);

  const start = async () => {
    if (!datasetId) return;
    setError(undefined);
    try {
      setJobId((await api.runEvaluation(datasetId, splits, rerun)).id);
    } catch (err) {
      setError(err as Error);
    }
  };

  if (!datasetId) return <Spinner />;
  return (
    <div className="grid gap-6 xl:grid-cols-[20rem_1fr]">
      <div className="space-y-6">
        <Card title="Run an evaluation">
          <SplitSelector value={splits} onChange={setSplits} />
          <label className="mt-3 flex items-center gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={rerun} onChange={(e) => setRerun(e.target.checked)} />
            Re-run inference first (otherwise stored predictions are reused)
          </label>
          <div className="mt-3">
            <Button onClick={() => void start()} disabled={splits.length === 0 || job?.status === "running" || job?.status === "queued"}>
              Evaluate
            </Button>
          </div>
          {error && (
            <div className="mt-3">
              <ErrorState error={error} />
            </div>
          )}
          {job && (
            <div className="mt-3 rounded-lg bg-slate-50 p-3">
              <JobStatus job={job} />
            </div>
          )}
        </Card>
        <Card title="History">
          {list.data && list.data.length === 0 && <EmptyState>No evaluations yet.</EmptyState>}
          <ul className="space-y-1">
            {list.data?.map((e) => (
              <li key={e.evaluation_id}>
                <button
                  type="button"
                  onClick={() => setSelected(e.evaluation_id)}
                  className={cx(
                    "w-full rounded-lg px-3 py-2 text-left text-sm",
                    selected === e.evaluation_id ? "bg-brand-50 text-brand-700" : "hover:bg-slate-50",
                  )}
                >
                  <div className="font-medium">{e.splits.join(", ")}</div>
                  <div className="text-xs text-slate-500">
                    P {formatPercent(e.edge_precision)} · cov {formatPercent(e.coverage)} · {formatDate(e.created_at)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <div>
        {report.error && <ErrorState error={report.error} onRetry={report.reload} />}
        {report.loading && <Spinner />}
        {!selected && !report.loading && <EmptyState>Run an evaluation to see metrics against hidden ground truth.</EmptyState>}
        {report.data && <ReportView report={report.data.report} />}
      </div>
    </div>
  );
}
