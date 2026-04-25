"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export interface UseApiDataOptions {
  /** Poll interval in milliseconds. Omit for single fetch. */
  intervalMs?: number;
  /** Set to false to skip fetching and use fallback immediately (demo / feature-flag). */
  enabled?: boolean;
}

export interface UseApiDataResult<T> {
  data: T;
  loading: boolean;
  /** Error message when the last fetch failed. null when ok. */
  error: string | null;
  /** True when displaying fallback mock data due to backend unavailability. */
  isDemo: boolean;
  refetch: () => void;
}

/**
 * Generic data-fetching hook.
 * - On success: returns real API data.
 * - On error: logs once, returns `fallback`, sets `isDemo = true`.
 * - Supports polling via `intervalMs`.
 * - `enabled = false` skips fetch entirely (returns fallback immediately).
 *
 * @example
 *   const { data, loading, isDemo, refetch } = useApiData(getStats, mockStats);
 *   const { data: events } = useApiData(getEvents, mockEvents, { intervalMs: 5000 });
 */
export function useApiData<T>(
  fetcher: () => Promise<T>,
  fallback: T,
  options: UseApiDataOptions = {},
): UseApiDataResult<T> {
  const { intervalMs, enabled = true } = options;

  const [data, setData] = useState<T>(fallback);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(!enabled);

  // Keep latest fetcher in a ref so the effect doesn't need to re-subscribe
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // Keep fallback in a ref so we don't cause extra re-renders
  const fallbackRef = useRef(fallback);

  const doFetch = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
      setIsDemo(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro de conexão com o backend";
      console.warn("[useApiData] fetch failed, using fallback:", msg);
      setError(msg);
      setIsDemo(true);
      // Do NOT reset data — keep previous real data or the fallback
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setData(fallbackRef.current);
      setIsDemo(true);
      setLoading(false);
      return;
    }

    setLoading(true);
    void doFetch();

    if (!intervalMs) return;
    const id = setInterval(() => void doFetch(), intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs, doFetch]);

  return { data, loading, error, isDemo, refetch: doFetch };
}
