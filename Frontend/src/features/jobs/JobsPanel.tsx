// Recent background jobs with live status
"use client";

import { useEffect, useState } from "react";

import { Badge, Card, EmptyState, ProgressBar } from "@/components/ui";
import { api } from "@/lib/api/endpoints";
import type { Job } from "@/lib/api/types";
import { formatDate, humanize } from "@/lib/format";

const STATUS_TONE = { queued: "neutral", running: "blue", succeeded: "green", failed: "red" } as const;

export function JobStatus({ job }: { job: Job }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="font-medium text-slate-700">{humanize(job.kind)}</span>
        <Badge tone={STATUS_TONE[job.status]}>{job.status}</Badge>
      </div>
      {job.status === "running" && <ProgressBar value={job.progress} />}
      {job.message && <div className="text-xs text-slate-500">{job.message}</div>}
      {job.error && <div className="text-xs text-rose-700">{job.error}</div>}
    </div>
  );
}

export function JobsPanel() {
  const [jobs, setJobs] = useState<Job[]>([]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const list = await api.jobs();
        if (!cancelled) setJobs(list.slice(0, 8));
      } catch {
      }
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <Card title="Background jobs">
      {jobs.length === 0 ? (
        <EmptyState>No jobs yet. Generation, split inference and evaluations run here.</EmptyState>
      ) : (
        <ul className="space-y-4">
          {jobs.map((job) => (
            <li key={job.id}>
              <JobStatus job={job} />
              <div className="mt-0.5 text-[11px] text-slate-400">
                {job.id} · {formatDate(job.created_at)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
