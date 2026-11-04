// Form that starts a dataset generation job
"use client";

import { useState, type FormEvent } from "react";

import { Button, Card, ErrorState, Field, inputClass } from "@/components/ui";
import { JobStatus } from "@/features/jobs/JobsPanel";
import { api } from "@/lib/api/endpoints";
import type { GenerateDatasetRequest } from "@/lib/api/types";
import { useAsync, useJob } from "@/lib/hooks";

import { useDataset } from "./DatasetContext";

const DEFAULTS: GenerateDatasetRequest = {
  dataset_id: "demo",
  companies: 20,
  min_employees_per_company: 100,
  target_employees: 4000,
  seed: 42,
  noise_profile: "medium_noise",
  challenge_noise_profile: "enterprise_complexity",
  overwrite: false,
};

export function GenerateDatasetForm() {
  const { refresh, setDatasetId } = useDataset();
  const profiles = useAsync(() => api.noiseProfiles(), []);
  const [form, setForm] = useState(DEFAULTS);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<Error>();
  const job = useJob(jobId, (finished) => {
    if (finished.status === "succeeded") {
      void refresh().then(() => setDatasetId(form.dataset_id));
    }
  });

  const update = <K extends keyof GenerateDatasetRequest>(key: K, value: GenerateDatasetRequest[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      const created = await api.generateDataset(form);
      setJobId(created.id);
    } catch (err) {
      setError(err as Error);
    }
  };

  const running = job?.status === "queued" || job?.status === "running";
  const names = profiles.data?.map((p) => p.name) ?? [DEFAULTS.noise_profile, DEFAULTS.challenge_noise_profile];

  return (
    <Card title="Generate a dataset">
      <form className="grid grid-cols-2 gap-3" onSubmit={submit}>
        <Field label="Dataset name">
          <input className={inputClass} value={form.dataset_id} onChange={(e) => update("dataset_id", e.target.value)} />
        </Field>
        <Field label="Seed">
          <input className={inputClass} type="number" value={form.seed} onChange={(e) => update("seed", Number(e.target.value))} />
        </Field>
        <Field label="Companies">
          <input className={inputClass} type="number" min={1} value={form.companies} onChange={(e) => update("companies", Number(e.target.value))} />
        </Field>
        <Field label="Target employees (floor)">
          <input className={inputClass} type="number" min={1} value={form.target_employees} onChange={(e) => update("target_employees", Number(e.target.value))} />
        </Field>
        <Field label="Noise profile">
          <select className={inputClass} value={form.noise_profile} onChange={(e) => update("noise_profile", e.target.value)}>
            {names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </Field>
        <Field label="Challenge noise profile">
          <select className={inputClass} value={form.challenge_noise_profile} onChange={(e) => update("challenge_noise_profile", e.target.value)}>
            {names.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </Field>
        <label className="col-span-2 flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={form.overwrite} onChange={(e) => update("overwrite", e.target.checked)} />
          Overwrite an existing dataset with the same name
        </label>
        <div className="col-span-2 flex items-center gap-3">
          <Button type="submit" disabled={running}>
            {running ? "Generating…" : "Generate"}
          </Button>
          <span className="text-xs text-slate-500">Runs the DataGenerator pipeline in the backend, including validation.</span>
        </div>
      </form>
      {error && (
        <div className="mt-3">
          <ErrorState error={error} />
        </div>
      )}
      {job && (
        <div className="mt-4 rounded-lg bg-slate-50 p-3">
          <JobStatus job={job} />
        </div>
      )}
    </Card>
  );
}
