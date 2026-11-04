// Dashboard: dataset stats, distributions, latest evaluation and generation
"use client";

import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner, StatTile, TextLink } from "@/components/ui";
import { BarList } from "@/features/charts/BarList";
import { useDataset } from "@/features/datasets/DatasetContext";
import { GenerateDatasetForm } from "@/features/datasets/GenerateDatasetForm";
import { JobsPanel } from "@/features/jobs/JobsPanel";
import { api } from "@/lib/api/endpoints";
import { formatDate, formatNumber, formatPercent, humanize } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

export default function DashboardPage() {
  const { datasetId, error: datasetsError, loading, refresh } = useDataset();
  const detail = useAsync(datasetId ? () => api.dataset(datasetId) : null, [datasetId]);
  const evaluations = useAsync(datasetId ? () => api.evaluations(datasetId) : null, [datasetId]);
  const latest = evaluations.data?.[0];

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Synthetic org datasets, inferred reporting lines and how accurate they are."
        actions={
          datasetId && (
            <Button
              variant="secondary"
              onClick={() => {
                void api.validateDataset(datasetId);
              }}
            >
              Validate dataset
            </Button>
          )
        }
      />
      {datasetsError && <ErrorState error={datasetsError} onRetry={() => void refresh()} />}
      {loading && <Spinner />}
      {!loading && !datasetsError && !datasetId && (
        <EmptyState>No datasets yet. Generate one below, or run `make generate` in Backend/.</EmptyState>
      )}

      {detail.data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <StatTile label="Companies" value={formatNumber(detail.data.company_count)} />
            <StatTile label="Employees" value={formatNumber(detail.data.employee_count)} hint={`${formatNumber(detail.data.departed_employee_count)} departed in stale sources`} />
            <StatTile label="Observations" value={formatNumber(detail.data.observation_count)} hint="from 5 sources" />
            <StatTile label="Noise" value={humanize(detail.data.noise_profile)} hint={`challenge: ${humanize(detail.data.challenge_noise_profile)}`} />
            <StatTile
              label="Latest edge precision"
              value={latest ? formatPercent(latest.edge_precision) : "—"}
              hint={latest ? `coverage ${formatPercent(latest.coverage)} on ${latest.splits.join(", ")}` : <TextLink href="/evaluation">Run an evaluation</TextLink>}
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-3">
            <Card title="Splits (company-level)">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-1">Split</th>
                    <th className="py-1 text-right">Companies</th>
                    <th className="py-1 text-right">Employees</th>
                    <th className="py-1 text-right">Inferred</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(detail.data.split_distribution).map(([split, row]) => (
                    <tr key={split} className="border-t border-slate-100">
                      <td className="py-1.5 font-medium">{split}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatNumber(row.companies)}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatNumber(row.employees)}</td>
                      <td className="py-1.5 text-right">{detail.data?.inferred_splits.includes(split) ? "yes" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-slate-500">Generated {formatDate(detail.data.generation_timestamp)} with seed {detail.data.random_seed}.</p>
            </Card>
            <Card title="Industries">
              <BarList data={detail.data.industry_distribution} />
            </Card>
            <Card title="Company sizes">
              <BarList data={Object.fromEntries(Object.entries(detail.data.company_size_distribution).map(([k, v]) => [humanize(k), v]))} />
              <div className="mt-5 text-xs font-semibold uppercase text-slate-500">Organizational archetypes</div>
              <div className="mt-2">
                <BarList data={Object.fromEntries(Object.entries(detail.data.archetype_distribution).map(([k, v]) => [humanize(k), v]))} />
              </div>
            </Card>
          </div>
        </div>
      )}
      {detail.error && <ErrorState error={detail.error} onRetry={detail.reload} />}

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <GenerateDatasetForm />
        <JobsPanel />
      </div>
    </>
  );
}
