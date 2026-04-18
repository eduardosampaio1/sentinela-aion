"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type { Stats } from "./types";
import type { ModuleStats, DecisionDistribution, OperationalState } from "./mock-data";
import {
  mockStats,
  mockModuleStats,
  mockDistribution,
  mockOperationalState,
} from "./mock-data";

// ═══════════════════════════════════════════
// Simulated real-time data with random drift
// ═══════════════════════════════════════════

function jitter(base: number, pct: number): number {
  const delta = base * (pct / 100);
  return Math.round(base + (Math.random() - 0.4) * delta * 2);
}

function jitterFloat(base: number, pct: number): number {
  const delta = base * (pct / 100);
  return +(base + (Math.random() - 0.4) * delta * 2).toFixed(2);
}

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val));
}

export interface RealtimeData {
  stats: Stats;
  modules: ModuleStats;
  distribution: DecisionDistribution;
  operational: OperationalState;
  lastUpdate: number;
}

function generateTick(prev: RealtimeData): RealtimeData {
  const newBypasses = jitter(prev.stats.bypasses, 2);
  const newRoutes = jitter(prev.stats.routes, 2);
  const newBlocks = jitter(prev.stats.blocks, 3);
  const newTotal = newBypasses + newRoutes + newBlocks + prev.stats.errors;

  const stats: Stats = {
    ...prev.stats,
    total_requests: newTotal,
    bypasses: newBypasses,
    routes: newRoutes,
    blocks: newBlocks,
    tokens_saved: jitter(prev.stats.tokens_saved, 1),
    cost_saved: jitterFloat(prev.stats.cost_saved, 2),
    avg_latency_ms: clamp(jitter(prev.stats.avg_latency_ms, 5), 80, 300),
  };

  const nomosDecisions = jitter(prev.modules.nomos.decisions_today, 2);
  const nomosLight = Math.round(nomosDecisions * 0.78);

  // Cache jitter — hits/misses always grow, hit_rate wobbles slightly
  const newHits = prev.modules.cache.hits + (Math.random() > 0.3 ? Math.floor(Math.random() * 4) : 0);
  const newMisses = prev.modules.cache.misses + (Math.random() > 0.5 ? Math.floor(Math.random() * 3) : 0);
  const newCacheTotal = newHits + newMisses;

  const modules: ModuleStats = {
    nomos: {
      decisions_today: nomosDecisions,
      routes_to_light: nomosLight,
      routes_to_premium: nomosDecisions - nomosLight,
      avg_decision_ms: clamp(jitter(prev.modules.nomos.avg_decision_ms, 15), 1, 8),
      cost_optimized: jitterFloat(prev.modules.nomos.cost_optimized, 2),
      classifier_method: prev.modules.nomos.classifier_method,
    },
    estixe: {
      bypasses_today: jitter(prev.modules.estixe.bypasses_today, 2),
      blocks_today: jitter(prev.modules.estixe.blocks_today, 3),
      threats_detected: prev.modules.estixe.threats_detected + (Math.random() > 0.9 ? 1 : 0),
      tokens_saved: jitter(prev.modules.estixe.tokens_saved, 1),
      cost_avoided: jitterFloat(prev.modules.estixe.cost_avoided, 2),
      false_positives_avoided: prev.modules.estixe.false_positives_avoided + (Math.random() > 0.85 ? 1 : 0),
    },
    metis: {
      optimizations_today: jitter(prev.modules.metis.optimizations_today, 2),
      tokens_compressed: jitter(prev.modules.metis.tokens_compressed, 1),
      avg_reduction_pct: clamp(jitter(prev.modules.metis.avg_reduction_pct, 5), 15, 35),
      cost_saved: jitterFloat(prev.modules.metis.cost_saved, 2),
      rewrites_applied: prev.modules.metis.rewrites_applied + (Math.random() > 0.7 ? 1 : 0),
    },
    cache: {
      ...prev.modules.cache,
      hits: newHits,
      misses: newMisses,
      hit_rate: newCacheTotal > 0 ? +(newHits / newCacheTotal).toFixed(4) : 0,
      total_entries: prev.modules.cache.total_entries + (Math.random() > 0.6 ? 1 : 0),
      invalidations: prev.modules.cache.invalidations + (Math.random() > 0.95 ? 1 : 0),
    },
  };

  // Distribution stays mostly stable with tiny wobble
  const bypassPct = clamp(prev.distribution.bypass_pct + (Math.random() > 0.5 ? 1 : -1), 35, 42);
  const lightPct = clamp(prev.distribution.light_model_pct + (Math.random() > 0.5 ? 1 : -1), 30, 38);
  const remaining = 100 - bypassPct - lightPct - prev.distribution.fallback_pct - prev.distribution.blocked_pct;

  const distribution: DecisionDistribution = {
    bypass_pct: bypassPct,
    light_model_pct: lightPct,
    standard_model_pct: Math.round(remaining * 0.72),
    premium_model_pct: Math.round(remaining * 0.28),
    fallback_pct: prev.distribution.fallback_pct,
    blocked_pct: prev.distribution.blocked_pct,
  };

  return {
    stats,
    modules,
    distribution,
    operational: prev.operational,
    lastUpdate: Date.now(),
  };
}

export function useRealtimeStats(intervalMs = 3000, enabled = true): RealtimeData {
  const [data, setData] = useState<RealtimeData>({
    stats: mockStats,
    modules: mockModuleStats,
    distribution: mockDistribution,
    operational: mockOperationalState,
    lastUpdate: Date.now(),
  });

  const dataRef = useRef(data);
  dataRef.current = data;

  const tick = useCallback(() => {
    setData((prev) => generateTick(prev));
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [tick, intervalMs, enabled]);

  return data;
}
