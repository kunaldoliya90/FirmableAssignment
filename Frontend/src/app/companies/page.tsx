// Company explorer page
import { PageHeader } from "@/components/ui";
import { CompanyExplorer } from "@/features/companies/CompanyExplorer";

export default function CompaniesPage() {
  return (
    <>
      <PageHeader title="Company explorer" subtitle="Browse the observed companies. Open one to infer and explore its org chart." />
      <CompanyExplorer />
    </>
  );
}
