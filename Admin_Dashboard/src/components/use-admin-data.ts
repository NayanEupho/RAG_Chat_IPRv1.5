"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface DataState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

export function useAdminData<T>(loader: () => Promise<T>, intervalMs = 10000): DataState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);

  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const next = await loaderRef.current();
      setData(next);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Unable to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const handle = window.setInterval(() => {
      void refresh();
    }, intervalMs);
    return () => window.clearInterval(handle);
  }, [intervalMs, refresh]);

  return { data, error, loading, refresh };
}
