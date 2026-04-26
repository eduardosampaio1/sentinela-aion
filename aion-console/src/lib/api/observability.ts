import type { Stats, AionEvent, CacheStats } from "@/lib/types";
import { fetchApi, transformStats, transformEvent } from "./_core";
import type { RawStats, RawEvent } from "./_core";

export interface HealthInfo {
  status: string;
  ready?: boolean;
  mode?: string;                  // pipeline mode: normal | degraded | safe
  aion_mode?: string;             // deployment mode: poc_decision | poc_transparent | ...
  executes_llm?: boolean;
  telemetry_enabled?: boolean;
  collective_enabled?: boolean;
  active_modules?: string[];
}

export async function getHealth(): Promise<HealthInfo> {
  return fetchApi("/health");
}

export async function getStats(): Promise<Stats> {
  const raw = await fetchApi<RawStats>("/v1/stats");
  return transformStats(raw);
}

export async function getEvents(limit = 50): Promise<AionEvent[]> {
  const raw = await fetchApi<RawEvent[]>(`/v1/events?limit=${limit}`);
  return (Array.isArray(raw) ? raw : []).map(transformEvent);
}

export async function getCacheStats(): Promise<CacheStats> {
  return fetchApi("/v1/cache/stats");
}

export async function explainRequest(requestId: string): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/explain/${requestId}`);
}
