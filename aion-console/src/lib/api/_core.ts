/**
 * Internal module — import only within lib/api/. Never import from components.
 * Provides the fetch helper, tenant state, and response transformers.
 */
import type { Stats, AionEvent, BudgetSummary } from "@/lib/types";

/**
 * All requests from client components go through the Next.js server-side proxy
 * at /api/proxy, which adds Authorization: Bearer <AION_API_KEY> securely.
 * AION_API_KEY never appears in the browser bundle.
 *
 * For server-side rendering (rare in this SPA), the proxy path also works
 * because Next.js resolves absolute URLs using the deploy origin.
 */
export const API_BASE = "/api/proxy";

let _activeTenant = process.env.NEXT_PUBLIC_AION_TENANT ?? "default";

export function setActiveTenant(tenant: string) {
  _activeTenant = tenant;
}

export function getActiveTenant(): string {
  return _activeTenant;
}

export async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    // Tenant header is forwarded by the proxy to the backend
    "X-Aion-Tenant": _activeTenant,
  };
  // Authorization is NOT added here — it is injected server-side in /api/proxy/[...path]/route.ts
  // so AION_API_KEY never leaks into the browser bundle.

  const res = await fetch(`${API_BASE}${path}`, {
    headers: { ...headers, ...(options?.headers as Record<string, string> | undefined) },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`AION API error: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ─── Transformers ─────────────────────────────────────────────────────────────
// Backend field names differ from frontend types. These functions normalize
// responses so all consumers receive the exact shape defined in types.ts.

export interface RawStats {
  total_events?: number;
  bypasses?: number;
  blocks?: number;
  passthroughs?: number;
  bypass_rate?: number;
  total_tokens_saved?: number;
  total_cost_saved?: number;
  avg_latency_ms?: number;
}

export function transformStats(raw: RawStats): Stats {
  const bypasses = raw.bypasses ?? 0;
  const blocks = raw.blocks ?? 0;
  const routes = raw.passthroughs ?? 0;
  return {
    total_requests: raw.total_events ?? bypasses + blocks + routes,
    bypasses,
    routes,
    blocks,
    errors: 0,
    tokens_saved: raw.total_tokens_saved ?? 0,
    cost_saved: raw.total_cost_saved ?? 0,
    avg_latency_ms: raw.avg_latency_ms ?? 0,
    top_model: "",
  };
}

const DECISION_MAP: Record<string, AionEvent["decision"]> = {
  continue: "route",
  route: "route",
  bypass: "bypass",
  block: "block",
  fallback: "fallback",
  error: "error",
};

const MODULE_MAP: Record<string, AionEvent["module"]> = {
  estixe: "ESTIXE",
  nomos: "NOMOS",
  metis: "METIS",
  ESTIXE: "ESTIXE",
  NOMOS: "NOMOS",
  METIS: "METIS",
};

export interface RawEvent {
  request_id?: string;
  id?: string;
  timestamp?: number | string;
  tenant?: string;
  input?: string;
  decision?: string;
  module?: string;
  model_used?: string;
  tokens_saved?: number;
  cost_saved?: number;
  response_time_ms?: number;
  latency_ms?: number;
  metadata?: Record<string, unknown>;
}

export function transformEvent(raw: RawEvent): AionEvent {
  const tsRaw = raw.timestamp;
  const timestamp =
    typeof tsRaw === "number"
      ? new Date(tsRaw * 1000).toISOString()
      : typeof tsRaw === "string"
      ? tsRaw
      : new Date().toISOString();

  return {
    id: raw.request_id ?? raw.id ?? "",
    timestamp,
    tenant: raw.tenant ?? _activeTenant,
    input: raw.input ?? "",
    decision: DECISION_MAP[raw.decision ?? ""] ?? "route",
    module: MODULE_MAP[raw.module ?? ""] ?? null,
    policy_applied: (raw.metadata?.detected_intent as string) ?? null,
    model_used: raw.model_used ?? null,
    tokens_used: raw.tokens_saved ?? null,
    cost: raw.cost_saved ?? null,
    response_time_ms: raw.response_time_ms ?? raw.latency_ms ?? 0,
    error: null,
    output: null,
  };
}

export interface RawBudgetStatus {
  tenant?: string;
  today_spend?: number;
  month_spend?: number;
  daily_cap?: number | null;
  monthly_cap?: number | null;
  daily_cap_pct?: number | null;
  cap_reached?: boolean;
  alert_active?: boolean;
  on_cap_reached?: string;
  budget_enabled?: boolean;
}

export function transformBudgetStatus(raw: RawBudgetStatus, avoidedCost = 0): BudgetSummary {
  const monthlyBudget = raw.monthly_cap ?? 0;
  const usedAmount = raw.month_spend ?? 0;
  const usedPct =
    monthlyBudget > 0
      ? Math.round((usedAmount / monthlyBudget) * 1000) / 10
      : raw.daily_cap_pct ?? 0;

  return {
    monthly_budget: monthlyBudget,
    used_brl: usedAmount,
    used_pct: usedPct,
    avoided_cost: avoidedCost,
    alerts: raw.alert_active ? 1 : 0,
    downgrades: 0,
    caps: [],
  };
}
