"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getHealth, getStats, getEvents, getEconomics } from "./api";
import type { Stats, AionEvent } from "./types";
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
 * Hook that polls the AION backend for real data.
 * Falls back to mock data if backend is unreachable.
 */
export function useAionData(intervalMs = 3000, enabled = true): AionLiveData {
  const [data, setData] = useState<AionLiveData>(INITIAL);
  const mountedRef = useRef(true);

  const fetchAll = useCallback(async () => {
    try {
      const [health, stats, events, economics] = await Promise.all([
        getHealth().catch(() => null),
        getStats().catch(() => null),
        getEvents(20).catch(() => []),
        getEconomics().catch(() => null),
      ]);

      if (!mountedRef.current) return;

      // Map backend data to our UI format
      const mappedStats: Stats = stats
        ? {
            total_requests: (stats as any).total_requests ?? (stats as any).passthroughs + (stats as any).bypasses + (stats as any).blocks,
            bypasses: (stats as any).bypasses ?? 0,
            routes: (stats as any).passthroughs ?? 0,
            blocks: (stats as any).blocks ?? 0,
            errors: 0,
            tokens_saved: (economics as any)?.tokens_saved ?? 0,
            cost_saved: (economics as any)?.cost_saved_usd ?? 0,
            avg_latency_ms: (stats as any).avg_latency_ms ?? 0,
            top_model: "gpt-4o-mini",
          }
        : mockStats;

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

      const mode = (health as any)?.mode ?? "unknown";
      const operational: OperationalState = {
        mode: "balanced",
        mode_label: mode === "normal" ? "Operacional" : mode === "safe" ? "Safe Mode" : mode === "degraded" ? "Degradado" : "Desconhecido",
        mode_description: mode === "normal" ? "Todos os módulos ativos" : mode === "safe" ? "Módulos bypassed" : "Degradação parcial",
        active_guardrails: (health as any)?.active_modules?.length ?? 0,
        total_guardrails: 3,
        uptime_hours: 0,
      };

      setData({
        stats: mappedStats,
        modules: mockModuleStats, // Module-level stats not available from API yet
        distribution,
        operational,
        events: events as AionEvent[],
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

    fetchAll(); // immediate first fetch

    const id = setInterval(fetchAll, intervalMs);
    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [fetchAll, intervalMs, enabled]);

  return data;
}
