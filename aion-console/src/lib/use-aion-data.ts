"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getHealth, getStats, getEvents, getEconomics, getCacheStats } from "./api";
import type { Stats, AionEvent, CacheStats } from "./types";
import type { ModuleStats, DecisionDistribution, OperationalState } from "./mock-data";
import {
  mockStats,
  mockModuleStats,
  mockDistribution,
  mockOperationalState,
} from "./mock-data";

export interface AionLiveData {
  stats: Stats;
  modules: ModuleStats;
  distribution: DecisionDistribution;
  operational: OperationalState;
  events: AionEvent[];
  lastUpdate: number;
  connected: boolean;
  error: string | null;
}

const INITIAL: AionLiveData = {
  stats: mockStats,
  modules: mockModuleStats,
  distribution: mockDistribution,
  operational: mockOperationalState,
  events: [],
  lastUpdate: Date.now(),
  connected: false,
  error: null,
};

/**
 * Hook that polls the AION backend for live dashboard data.
 * Falls back gracefully to mock data if the backend is unreachable.
 *
 * NOTE: getStats() and getEvents() already apply transformers in api.ts,
 * so the values returned here are correctly typed — no `any` casts needed.
 */
export function useAionData(intervalMs = 3000, enabled = true): AionLiveData {
  const [data, setData] = useState<AionLiveData>(INITIAL);
  const mountedRef = useRef(true);

  const fetchAll = useCallback(async () => {
    try {
      const [health, stats, events, economics, cacheData] = await Promise.all([
        getHealth().catch(() => null),
        getStats().catch(() => null),
        getEvents(20).catch((): AionEvent[] => []),
        getEconomics().catch(() => null),
        getCacheStats().catch(() => null),
      ]);

      if (!mountedRef.current) return;

      // stats is already a correctly-typed Stats object (transformer ran in getStats())
      const mappedStats: Stats = stats ?? {
        ...mockStats,
        // Supplement token/cost savings from economics endpoint when available
        tokens_saved: economics
          ? ((economics.tokens_saved as number) ?? mockStats.tokens_saved)
          : mockStats.tokens_saved,
        cost_saved: economics
          ? ((economics.cost_saved_usd as number) ?? mockStats.cost_saved)
          : mockStats.cost_saved,
      };

      const total = mappedStats.total_requests || 1;
      const bypassPct = Math.round((mappedStats.bypasses / total) * 100);
      const blockPct = Math.round((mappedStats.blocks / total) * 100);
      const routePct = 100 - bypassPct - blockPct;

      const distribution: DecisionDistribution = {
        bypass_pct: bypassPct,
        light_model_pct: Math.round(routePct * 0.6),
        standard_model_pct: Math.round(routePct * 0.3),
        premium_model_pct: Math.round(routePct * 0.1),
        fallback_pct: 0,
        blocked_pct: blockPct,
      };

      const healthStatus = (health?.status as string) ?? "unknown";
      const operational: OperationalState = {
        mode: "balanced",
        mode_label:
          healthStatus === "healthy" ? "Operacional"
          : healthStatus === "safe" ? "Safe Mode"
          : healthStatus === "degraded" ? "Degradado"
          : "Desconhecido",
        mode_description:
          healthStatus === "healthy" ? "Todos os módulos ativos"
          : healthStatus === "safe" ? "Módulos em modo passagem"
          : "Degradação parcial detectada",
        active_guardrails: 3,
        total_guardrails: 3,
        uptime_hours: 0,
      };

      // Merge real cache stats into module stats
      const modules: ModuleStats = { ...mockModuleStats };
      if (cacheData) {
        const c = cacheData as CacheStats;
        modules.cache = {
          enabled: c.enabled,
          hits: c.hits,
          misses: c.misses,
          hit_rate: c.hit_rate,
          invalidations: c.invalidations,
          evictions: c.evictions,
          total_entries: c.total_entries,
          entries_by_tenant: c.entries_by_tenant,
        };
      }

      setData({
        stats: mappedStats,
        modules,
        distribution,
        operational,
        events,
        lastUpdate: Date.now(),
        connected: true,
        error: null,
      });
    } catch (err) {
      if (!mountedRef.current) return;
      setData((prev) => ({
        ...prev,
        connected: false,
        error: err instanceof Error ? err.message : "Connection failed",
      }));
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return;

    void fetchAll();

    const id = setInterval(() => void fetchAll(), intervalMs);
    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [fetchAll, intervalMs, enabled]);

  return data;
}
