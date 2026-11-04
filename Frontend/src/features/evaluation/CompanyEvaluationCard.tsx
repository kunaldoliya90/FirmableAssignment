// Evaluation metrics for a single company
"use client";

import { Card, ErrorState, Spinner } from "@/components/ui";
import { api } from "@/lib/api/endpoints";
import { formatDecimal } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

import { MetricsGrid } from "./MetricsGrid";

export function CompanyEvaluationCard({ datasetId, companyId }: { datasetId: string; companyId: string }) {
  const evaluation = useAsync(() => api.companyEvaluation(datasetId, companyId), [datasetId, companyId]);
  return (
    <Card title="Accuracy against hidden ground truth">
      <p className="mb-4 text-sm text-slate-500">
        Computed by the evaluation service after inference finished. Only aggregate metrics are returned; true reporting lines never reach the
        browser.
      </p>
      {evaluation.error && <ErrorState error={evaluation.error} onRetry={evaluation.reload} />}
      {evaluation.loading && <Spinner />}
      {evaluation.data && (
        <>
          <MetricsGrid metrics={evaluation.data.metrics} />
          <p className="mt-4 text-xs text-slate-500">
            Calibration: ECE {formatDecimal(evaluation.data.metrics.calibration.expected_calibration_error ?? null)} · Brier{" "}
            {formatDecimal(evaluation.data.metrics.calibration.brier_score ?? null)}
          </p>
        </>
      )}
    </Card>
  );
}
