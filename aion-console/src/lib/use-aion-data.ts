"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getHealth, getStats, getEvents, getEconomics, getCacheStats, getEconomicsDaily } from "./api";
import type { Stats, AionEvent, CacheStats, SpendTrendPoint } from "./types";
import type { ModuleStats, DecisionDistribution, OperationalState } from "./mock-data";
import {
  mockStats,
  mockModuleStats,
  mockDistribution,
  mockOperationalState,
} from "./mock-data";

export interface ModelCostPoint {
  name: string;
  value: number;
  fill: string;
}

export interface AionLiveData {
  stats: Stats;
  modules: ModuleStats;
  distribution: DecisionDistribution;
  operational: OperationalState;
  events: AionEvent[];
  spendTrend: SpendTrendPoint[];
  modelCostDist: ModelCostPoint[];
  lastUpdate: number;
  connected: boolean;
  error: string | null;
}

const MODEL_COLORS = [
  "#0ea5e9", "#22c55e", "#f59e0b", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316",
];

const INITIAL: AionLiveData = {
  stats: mockStats,
  modules: mockModuleStats,
  distribution: mockDistribution,
  operational: mockOperationalState,
  events: [],
  spendTrend: [],
  modelCostDist: [],
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
      const [health, stats, events, economics, cacheData, dailyRows] = await Promise.all([
        getHealth().catch(() => null),
        getStats().catch(() => null),
        getEvents(20).catch((): AionEvent[] => []),
        getEconomics().catch(() => null),
        getCacheStats().catch(() => null),
        getEconomicsDaily(30).catch(() => []),
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

      // Build spendTrend from daily economics rows (sorted ascending by date)
      const spendTrend: SpendTrendPoint[] = dailyRows.map((r) => ({
        date: r.date,
        spend: r.total_cost_usd,
        avoided: r.total_savings_usd,
      }));

      // Build modelCostDist by aggregating by_model across all days
      const modelTotals: Record<string, number> = {};
      for (const row of dailyRows) {
        if (row.by_model && typeof row.by_model === "object") {
          for (const [model, data] of Object.entries(row.by_model)) {
            modelTotals[model] = (modelTotals[model] ?? 0) + (data.cost_usd ?? 0);
          }
        }
      }
      const modelCostDist: ModelCostPoint[] = Object.entries(modelTotals)
        .sort((a, b) => b[1] - a[1])
        .slice(0, MODEL_COLORS.length)
        .map(([name, value], i) => ({
          name,
          value: Math.round(value * 10000) / 10000,
          fill: MODEL_COLORS[i % MODEL_COLORS.length],
        }));

      setData({
        stats: mappedStats,
        modules,
        distribution,
        operational,
        events,
        spendTrend,
        modelCostDist,
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
