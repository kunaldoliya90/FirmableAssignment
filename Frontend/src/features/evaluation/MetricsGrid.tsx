// Headline edge metrics as stat tiles
import { StatTile } from "@/components/ui";
import type { EdgeMetrics } from "@/lib/api/types";
import { formatDecimal, formatNumber, formatPercent } from "@/lib/format";

export function MetricsGrid({ metrics }: { metrics: EdgeMetrics }) {
  const counts = metrics.counts;
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatTile label="Edge precision" value={formatPercent(metrics.edge_precision)} hint={`${formatNumber(counts.correct)} correct / ${formatNumber(counts.predicted)} answered`} />
      <StatTile label="Edge recall" value={formatPercent(metrics.edge_recall)} hint={`of ${formatNumber(counts.true_edges)} true edges`} />
      <StatTile label="Edge F1" value={formatPercent(metrics.edge_f1)} />
      <StatTile label="Coverage" value={formatPercent(metrics.coverage)} hint={`abstained on ${formatPercent(metrics.abstention_rate)}`} />
      <StatTile label="Wrong edges" value={formatNumber(counts.wrong)} hint={`${formatNumber(counts.wrong_on_root)} on roots · ${formatNumber(counts.departed_predicted)} on departed`} />
      <StatTile label="Penalized score" value={formatDecimal(metrics.penalized_score)} hint="(correct − 2 × wrong) / true edges" />
      <StatTile label="Departed (abstained)" value={formatNumber((counts.departed_evaluated ?? 0) - (counts.departed_predicted ?? 0))} hint={`of ${formatNumber(counts.departed_evaluated)} departed`} />
      <StatTile label="Missing predictions" value={formatNumber(counts.missing_predictions)} />
    </div>
  );
}
