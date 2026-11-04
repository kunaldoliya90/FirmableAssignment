// Data-loading hooks: useAsync and job polling
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api/endpoints";
import type { Job } from "./api/types";

export interface AsyncState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

export function useAsync<T>(load: (() => Promise<T>) | null, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(Boolean(load));
  const [tick, setTick] = useState(0);
  const call = useRef(0);

  useEffect(() => {
    if (!load) {
      setLoading(false);
      return;
    }
    const id = ++call.current;
    setLoading(true);
    setError(undefined);
    load()
      .then((value) => {
        if (id === call.current) setData(value);
      })
      .catch((err: unknown) => {
        if (id === call.current) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (id === call.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

export function useJob(jobId: string | null, onDone?: (job: Job) => void): Job | undefined {
  const [job, setJob] = useState<Job>();
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    if (!jobId) {
      setJob(undefined);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const current = await api.job(jobId);
        if (cancelled) return;
        setJob(current);
        if (current.status === "succeeded" || current.status === "failed") {
          done.current?.(current);
          return;
        }
      } catch {
      }
      timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);
  return job;
}
