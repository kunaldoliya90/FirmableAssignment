// Evaluation page
import { PageHeader } from "@/components/ui";
import { EvaluationDashboard } from "@/features/evaluation/EvaluationDashboard";

export default function EvaluationPage() {
  return (
    <>
      <PageHeader
        title="Evaluation"
        subtitle="Edge precision, recall, coverage and calibration of finished predictions against hidden ground truth. Wrong edges cost twice a correct one."
      />
      <EvaluationDashboard />
    </>
  );
}
