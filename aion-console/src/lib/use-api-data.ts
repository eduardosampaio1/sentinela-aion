"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export interface UseApiDataOptions<T = unknown> {
  /** Poll interval in milliseconds. Omit for single fetch. */
  intervalMs?: number;
  /** Set to false to skip fetching and use fallback immediately (demo / feature-flag). */
  enabled?: boolean;
  /**
   * Treat a successful fetch as "demo" when this predicate returns true.
   *
   * Closes M3: distinguishes "API responded with `[]` because the contract
   * is wrong" from "API responded with `[]` because there really is no
   * data" — without it, the UI shows an empty grid silently. Pass e.g.
   * `(d) => d.length === 0` to mark empty arrays as demo, surfacing the
   * `<DemoBanner>`.
   *
   * Default: never treat success as demo (preserves prior behavior).
   */
  treatEmptyAsDemo?: (data: T) => boolean;
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
  options: UseApiDataOptions<T> = {},
): UseApiDataResult<T> {
  const { intervalMs, enabled = true, treatEmptyAsDemo } = options;

  const [data, setData] = useState<T>(fallback);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(!enabled);

  // Keep latest fetcher in a ref so the effect doesn't need to re-subscribe
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // Keep fallback in a ref so we don't cause extra re-renders
  const fallbackRef = useRef(fallback);

  // Keep treatEmptyAsDemo in a ref to allow stable callback identity
  const treatEmptyRef = useRef(treatEmptyAsDemo);
  treatEmptyRef.current = treatEmptyAsDemo;

  const doFetch = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      // Surface contract drift: a successful fetch that the caller flags as
      // "empty" gets the same treatment as a failed fetch (M3 fix). The
      // `<DemoBanner>` wires off `isDemo`, so users see a hint when the
      // backend returned 200 but with no usable data.
      const looksEmpty = treatEmptyRef.current ? treatEmptyRef.current(result) : false;
      if (looksEmpty) {
        setData(result);
        setError(null);
        setIsDemo(true);
      } else {
        setData(result);
        setError(null);
        setIsDemo(false);
      }
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
