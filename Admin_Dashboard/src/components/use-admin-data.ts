"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface CacheRecord<T = unknown> {
  data: T;
  stale: boolean;
  updatedAt: number;
}

const cache = new Map<string, CacheRecord>();
const inflight = new Map<string, Promise<unknown>>();
const MAX_CACHE_SIZE = 150;

const UPDATED_EVENT = "admin-data-cache-updated";
const INVALIDATED_EVENT = "admin-data-invalidated";

interface InvalidationDetail {
  keys?: string[];
}

interface DataState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

export function invalidateAdminData(keys?: string[]): void {
  if (typeof window === "undefined") return;
  if (!keys?.length) {
    cache.forEach((record) => {
      record.stale = true;
    });
  } else {
    cache.forEach((record, key) => {
      if (matchesInvalidation(key, keys)) record.stale = true;
    });
  }
  window.dispatchEvent(new CustomEvent<InvalidationDetail>(INVALIDATED_EVENT, { detail: { keys } }));
}

export function setAdminDataCache<T>(key: string, data: T): void {
  cache.set(key, { data, stale: false, updatedAt: Date.now() });
  evictOldCacheEntries();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(UPDATED_EVENT, { detail: { key } }));
  }
}

export async function prefetchAdminData<T>(key: string, loader: () => Promise<T>, force = false): Promise<void> {
  if (!force && freshCached<T>(key)) return;
  if (inflight.has(key)) {
    await inflight.get(key);
    return;
  }
  const promise = loader()
    .then((data) => {
      setAdminDataCache(key, data);
      return data;
    })
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, promise);
  await promise;
}

function matchesInvalidation(cacheKey: string, keys?: string[]): boolean {
  if (!keys?.length) return true;
  return keys.some((key) => {
    if (key === cacheKey) return true;
    if (key.endsWith("*")) return cacheKey.startsWith(key.slice(0, -1));
    return false;
  });
}

function evictOldCacheEntries(): void {
  if (cache.size <= MAX_CACHE_SIZE) return;
  const removable = [...cache.entries()]
    .filter(([, record]) => record.stale)
    .sort((a, b) => a[1].updatedAt - b[1].updatedAt);
  const fallback = [...cache.entries()].sort((a, b) => a[1].updatedAt - b[1].updatedAt);
  const candidates = removable.length ? removable : fallback;
  for (const [key] of candidates.slice(0, Math.max(1, cache.size - MAX_CACHE_SIZE + 10))) {
    cache.delete(key);
  }
}

function freshCached<T>(key?: string): T | null {
  if (!key) return null;
  const record = cache.get(key);
  if (!record || record.stale) return null;
  return record.data as T;
}

export function useAdminData<T>(
  loader: () => Promise<T>,
  intervalMs = 10000,
  cacheKey?: string,
  enabled = true,
  keepPreviousData = false
): DataState<T> {
  const [data, setData] = useState<T | null>(() => (enabled ? freshCached<T>(cacheKey) : null));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled && !freshCached<T>(cacheKey));
  const loaderRef = useRef(loader);
  const keyRef = useRef(cacheKey);
  const enabledRef = useRef(enabled);
  const keepPreviousDataRef = useRef(keepPreviousData);
  const mountedRef = useRef(false);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);

  useEffect(() => {
    keyRef.current = cacheKey;
  }, [cacheKey]);

  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  useEffect(() => {
    keepPreviousDataRef.current = keepPreviousData;
  }, [keepPreviousData]);

  const refresh = useCallback(async () => {
    if (!enabledRef.current) {
      setLoading(false);
      return;
    }
    const requestSeq = ++requestSeqRef.current;
    try {
      setError(null);
      const key = keyRef.current;
      const next = key
        ? await (async () => {
            await prefetchAdminData(key, loaderRef.current, true);
            const record = cache.get(key);
            return record?.data as T;
          })()
        : await loaderRef.current();
      if (mountedRef.current && enabledRef.current && requestSeq === requestSeqRef.current) {
        setData(next);
      }
    } catch (caught: unknown) {
      if (mountedRef.current && enabledRef.current && requestSeq === requestSeqRef.current) {
        setError(caught instanceof Error ? caught.message : "Unable to load data");
      }
    } finally {
      if (mountedRef.current && requestSeq === requestSeqRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) {
      setLoading(false);
      return () => {
        mountedRef.current = false;
        requestSeqRef.current += 1;
      };
    }
    const cached = freshCached<T>(cacheKey);
    if (cached) {
      setData(cached);
      setLoading(false);
    } else {
      if (!keepPreviousDataRef.current) setData(null);
      setLoading(true);
      void refresh();
    }

    function handleUpdated(event: Event) {
      const key = (event as CustomEvent<{ key?: string }>).detail?.key;
      if (!enabledRef.current) return;
      if (!cacheKey || key !== cacheKey || !cache.has(cacheKey)) return;
      const record = cache.get(cacheKey);
      if (!record || record.stale) return;
      setData(record.data as T);
      setLoading(false);
    }

    function handleInvalidated(event: Event) {
      const keys = (event as CustomEvent<InvalidationDetail>).detail?.keys;
      if (!enabledRef.current) return;
      if (!cacheKey || matchesInvalidation(cacheKey, keys)) {
        if (!keepPreviousDataRef.current) setData(null);
        setLoading(true);
        void refresh();
      }
    }

    window.addEventListener(UPDATED_EVENT, handleUpdated);
    window.addEventListener(INVALIDATED_EVENT, handleInvalidated);

    const handle = intervalMs > 0 ? window.setInterval(() => void refresh(), intervalMs) : null;
    return () => {
      window.removeEventListener(UPDATED_EVENT, handleUpdated);
      window.removeEventListener(INVALIDATED_EVENT, handleInvalidated);
      if (handle) window.clearInterval(handle);
      mountedRef.current = false;
      requestSeqRef.current += 1;
    };
  }, [cacheKey, enabled, intervalMs, keepPreviousData, refresh]);

  return { data, error, loading, refresh };
}
