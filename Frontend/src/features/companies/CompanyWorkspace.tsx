// Company page tabs: org chart, unresolved, employees, evaluation
"use client";

import { useState } from "react";

import { Badge, Button, Card, cx, ErrorState, PageHeader, Spinner, StatTile } from "@/components/ui";
import { useDataset } from "@/features/datasets/DatasetContext";
import { EmployeeTable } from "@/features/employees/EmployeeTable";
import { CompanyEvaluationCard } from "@/features/evaluation/CompanyEvaluationCard";
import { OrgChartView } from "@/features/orgchart/OrgChartView";
import { UnresolvedTable } from "@/features/orgchart/UnresolvedTable";
import { api } from "@/lib/api/endpoints";
import { formatNumber, formatPercent, humanize } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

const TABS = ["Org chart", "Unresolved", "Employees", "Evaluation"] as const;
type Tab = (typeof TABS)[number];

export function CompanyWorkspace({ companyId, focusId }: { companyId: string; focusId?: string }) {
  const { datasetId } = useDataset();
  const [tab, setTab] = useState<Tab>("Org chart");
  const [version, setVersion] = useState(0);
  const company = useAsync(datasetId ? () => api.company(datasetId, companyId) : null, [datasetId, companyId, version]);
  const inference = useAsync(datasetId ? () => api.inferCompany(datasetId, companyId) : null, [datasetId, companyId, version]);
  const [refreshing, setRefreshing] = useState(false);

  if (!datasetId) return <Spinner />;
  if (company.error) return <ErrorState error={company.error} onRetry={company.reload} />;
  if (!company.data) return <Spinner />;
  const c = company.data;
  const stats = inference.data;

  const rerun = async () => {
    setRefreshing(true);
    try {
      await api.inferCompany(datasetId, companyId, true);
      setVersion((v) => v + 1);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <>
      <PageHeader
        title={c.company_name}
        subtitle={
          <>
            {c.industry} · {humanize(c.company_size_segment)} · HQ {c.headquarters} · {c.operating_regions.join(", ")} · <Badge>{c.split}</Badge>
          </>
        }
        actions={
          <Button variant="secondary" onClick={() => void rerun()} disabled={refreshing || inference.loading}>
            {refreshing ? "Re-running…" : "Re-run inference"}
          </Button>
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-6">
        <StatTile label="Employees" value={formatNumber(c.employee_count)} />
        <StatTile label="Observed people" value={formatNumber(c.observed_employee_count)} hint="incl. departed" />
        <StatTile label="Observations" value={formatNumber(c.observation_count)} />
        <StatTile label="Confident edges" value={stats ? formatNumber(stats.predicted_edges) : "…"} hint={stats ? `${formatPercent(stats.predicted_edges / stats.employees)} of people` : undefined} />
        <StatTile label="Abstentions" value={stats ? formatNumber(stats.abstentions) : "…"} hint={stats ? `threshold ${stats.confidence_threshold}` : undefined} />
        <StatTile label="Departed detected" value={stats ? formatNumber(stats.departed_detected) : "…"} hint={stats ? `${stats.elapsed_seconds}s inference` : undefined} />
      </div>
      {inference.error && <ErrorState error={inference.error} onRetry={inference.reload} />}

      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cx(
              "-mb-px border-b-2 px-4 py-2 text-sm font-medium",
              tab === t ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-700",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {inference.loading && !stats ? (
        <Spinner label="Running inference on observed records…" />
      ) : (
        <div key={version}>
          {tab === "Org chart" && (
            <Card>
              <OrgChartView datasetId={datasetId} companyId={companyId} focusId={focusId} />
            </Card>
          )}
          {tab === "Unresolved" && <UnresolvedTable datasetId={datasetId} companyId={companyId} />}
          {tab === "Employees" && <EmployeeTable datasetId={datasetId} companyId={companyId} />}
          {tab === "Evaluation" && <CompanyEvaluationCard datasetId={datasetId} companyId={companyId} />}
        </div>
      )}
      {stats && (
        <p className="mt-4 text-xs text-slate-500">
          Decisions: {Object.entries(stats.decision_reasons).map(([k, v]) => `${humanize(k)} ${formatNumber(v)}`).join(" · ")}
        </p>
      )}
    </>
  );
}
