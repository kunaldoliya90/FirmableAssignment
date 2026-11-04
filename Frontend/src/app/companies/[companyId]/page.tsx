// Company workspace page
"use client";

import { Suspense, use } from "react";
import { useSearchParams } from "next/navigation";

import { Spinner } from "@/components/ui";
import { CompanyWorkspace } from "@/features/companies/CompanyWorkspace";

function CompanyPageInner({ companyId }: { companyId: string }) {
  const focus = useSearchParams().get("focus") ?? undefined;
  return <CompanyWorkspace companyId={companyId} focusId={focus} />;
}

export default function CompanyPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  return (
    <Suspense fallback={<Spinner />}>
      <CompanyPageInner companyId={decodeURIComponent(companyId)} />
    </Suspense>
  );
}
