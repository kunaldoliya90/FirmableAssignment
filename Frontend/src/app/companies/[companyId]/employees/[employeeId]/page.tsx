// Employee detail page
"use client";

import { use } from "react";

import { EmployeeDetailView } from "@/features/employees/EmployeeDetailView";

export default function EmployeePage({ params }: { params: Promise<{ companyId: string; employeeId: string }> }) {
  const { companyId, employeeId } = use(params);
  return <EmployeeDetailView companyId={decodeURIComponent(companyId)} employeeId={decodeURIComponent(employeeId)} />;
}
