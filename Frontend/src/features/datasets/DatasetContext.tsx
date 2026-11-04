// Selected dataset, shared across pages and remembered in local storage
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "@/lib/api/endpoints";
import type { DatasetSummary } from "@/lib/api/types";

interface DatasetContextValue {
  datasets: DatasetSummary[];
  datasetId: string | null;
  dataset: DatasetSummary | undefined;
  setDatasetId: (id: string) => void;
  refresh: () => Promise<void>;
  error: Error | undefined;
  loading: boolean;
}

const DatasetContext = createContext<DatasetContextValue | null>(null);
const STORAGE_KEY = "firmable.dataset";

export function DatasetProvider({ children }: { children: ReactNode }) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setId] = useState<string | null>(null);
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const list = await api.datasets();
      setDatasets(list);
      setError(undefined);
      setId((current) => {
        let stored: string | null = null;
        try {
          stored = window.localStorage.getItem(STORAGE_KEY);
        } catch {
        }
        const preferred = current ?? stored;
        if (preferred && list.some((d) => d.dataset_id === preferred)) return preferred;
        return list[0]?.dataset_id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setDatasetId = useCallback((id: string) => {
    setId(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
    }
  }, []);

  const value = useMemo(
    () => ({
      datasets,
      datasetId,
      dataset: datasets.find((d) => d.dataset_id === datasetId),
      setDatasetId,
      refresh,
      error,
      loading,
    }),
    [datasets, datasetId, setDatasetId, refresh, error, loading],
  );
  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}

export function useDataset(): DatasetContextValue {
  const value = useContext(DatasetContext);
  if (!value) throw new Error("useDataset must be used inside <DatasetProvider>");
  return value;
}
