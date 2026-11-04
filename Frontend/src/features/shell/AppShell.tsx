// App frame: navigation, dataset selector and the dataset provider
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { cx, inputClass } from "@/components/ui";
import { DatasetProvider, useDataset } from "@/features/datasets/DatasetContext";
import { API_BASE_URL } from "@/lib/api/client";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/companies", label: "Companies" },
  { href: "/search", label: "Employee search" },
  { href: "/inference", label: "Inference" },
  { href: "/evaluation", label: "Evaluation" },
];

function DatasetSelector() {
  const { datasets, datasetId, setDatasetId, error } = useDataset();
  if (error) {
    return <span className="text-xs text-rose-600">API unreachable ({API_BASE_URL})</span>;
  }
  return (
    <label className="flex items-center gap-2 text-xs font-medium text-slate-500">
      Dataset
      <select
        aria-label="Dataset"
        className={inputClass}
        value={datasetId ?? ""}
        onChange={(e) => setDatasetId(e.target.value)}
        disabled={datasets.length === 0}
      >
        {datasets.length === 0 && <option value="">No datasets</option>}
        {datasets.map((d) => (
          <option key={d.dataset_id} value={d.dataset_id}>
            {d.dataset_id} ({d.company_count} companies)
          </option>
        ))}
      </select>
    </label>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <DatasetProvider>
      <div className="flex min-h-screen">
        <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
          <div className="px-5 py-5">
            <div className="text-lg font-semibold text-slate-900">OrgGraph</div>
            <div className="text-xs text-slate-500">Org-chart inference</div>
          </div>
          <nav className="flex flex-col gap-0.5 px-3">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cx(
                    "rounded-lg px-3 py-2 text-sm font-medium",
                    active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-6 py-3">
            <nav className="flex gap-3 text-sm md:hidden">
              {NAV.map((item) => (
                <Link key={item.href} href={item.href} className="text-slate-600">
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="hidden text-sm text-slate-500 md:block">Observed data only. Ground truth is used for evaluation alone.</div>
            <DatasetSelector />
          </header>
          <main className="min-w-0 flex-1 px-6 py-6">{children}</main>
        </div>
      </div>
    </DatasetProvider>
  );
}
