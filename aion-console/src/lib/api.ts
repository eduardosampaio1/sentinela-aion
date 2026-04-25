import type {
  Stats,
  AionEvent,
  BehaviorDial,
  ModelInfo,
  CacheStats,
  SuggestionsResponse,
  SuggestionApprovalResponse,
  Session,
  BudgetSummary,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_AION_API_URL ?? "http://localhost:8080";

let _activeTenant = process.env.NEXT_PUBLIC_AION_TENANT ?? "default";

export function setActiveTenant(tenant: string) {
  _activeTenant = tenant;
}

export function getActiveTenant(): string {
  return _activeTenant;
}

// ─── Core fetch helper ────────────────────────────────────────────────────────

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Aion-Tenant": _activeTenant,
  };
  const apiKey = process.env.NEXT_PUBLIC_AION_API_KEY;
  if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;

  const res = await fetch(`${API_BASE}${path}`, {
    headers: { ...headers, ...(options?.headers as Record<string, string> | undefined) },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`AION API error: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ─── Internal transformers ────────────────────────────────────────────────────
// Backend field names differ from frontend types. These functions normalize responses
// so all components receive the exact shape defined in types.ts.

interface RawStats {
  total_events?: number;
  bypasses?: number;
  blocks?: number;
  passthroughs?: number;
  bypass_rate?: number;
  total_tokens_saved?: number;
  total_cost_saved?: number;
  avg_latency_ms?: number;
}

function transformStats(raw: RawStats): Stats {
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

interface RawEvent {
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

function transformEvent(raw: RawEvent): AionEvent {
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

interface RawBudgetStatus {
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

function transformBudgetStatus(raw: RawBudgetStatus, avoidedCost = 0): BudgetSummary {
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

// ─── Health ───────────────────────────────────────────────────────────────────

export async function getHealth(): Promise<{ status: string; ready?: boolean }> {
  return fetchApi("/health");
}

// ─── Stats ────────────────────────────────────────────────────────────────────

export async function getStats(): Promise<Stats> {
  const raw = await fetchApi<RawStats>("/v1/stats");
  return transformStats(raw);
}

// ─── Events ───────────────────────────────────────────────────────────────────

export async function getEvents(limit = 50): Promise<AionEvent[]> {
  const raw = await fetchApi<RawEvent[]>(`/v1/events?limit=${limit}`);
  return (Array.isArray(raw) ? raw : []).map(transformEvent);
}

// ─── Behavior ─────────────────────────────────────────────────────────────────

export async function getBehavior(): Promise<BehaviorDial> {
  return fetchApi("/v1/behavior");
}

export async function setBehavior(dial: Partial<BehaviorDial>): Promise<BehaviorDial> {
  return fetchApi("/v1/behavior", {
    method: "PUT",
    body: JSON.stringify(dial),
  });
}

export async function resetBehavior(): Promise<void> {
  await fetchApi("/v1/behavior", { method: "DELETE" });
}

// ─── Models ───────────────────────────────────────────────────────────────────

export async function getModels(): Promise<ModelInfo[]> {
  const raw = await fetchApi<ModelInfo | ModelInfo[]>("/v1/models");
  return Array.isArray(raw) ? raw : [raw];
}

// ─── Pipeline topology ────────────────────────────────────────────────────────

export async function getPipelineTopology(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/pipeline");
}

// ─── Module toggle ────────────────────────────────────────────────────────────

export async function toggleModule(
  module: "estixe" | "nomos" | "metis",
  enabled: boolean,
): Promise<{ module: string; enabled: boolean }> {
  return fetchApi(`/v1/modules/${module}/toggle`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

// ─── Kill switch ──────────────────────────────────────────────────────────────

export async function getKillswitch(): Promise<{
  killswitch_active: boolean;
  reason?: string;
  expires_at?: number;
}> {
  return fetchApi("/v1/killswitch");
}

export async function activateKillswitch(
  reason: string,
  duration_seconds = 3600,
): Promise<{ killswitch_active: true; reason: string; expires_at: number }> {
  return fetchApi("/v1/killswitch", {
    method: "PUT",
    body: JSON.stringify({ reason, duration_seconds }),
  });
}

export async function deactivateKillswitch(): Promise<{ killswitch_active: false }> {
  return fetchApi("/v1/killswitch", { method: "DELETE" });
}

// ─── Overrides ────────────────────────────────────────────────────────────────

export async function getOverrides(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/overrides");
}

export async function setOverrides(
  overrides: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return fetchApi("/v1/overrides", {
    method: "PUT",
    body: JSON.stringify(overrides),
  });
}

export async function clearOverrides(): Promise<void> {
  await fetchApi("/v1/overrides", { method: "DELETE" });
}

// ─── Reload ───────────────────────────────────────────────────────────────────

export async function reloadIntents(): Promise<void> {
  await fetchApi("/v1/estixe/intents/reload", { method: "POST" });
}

export async function reloadPolicies(): Promise<void> {
  await fetchApi("/v1/estixe/policies/reload", { method: "POST" });
}

export async function reloadGuardrails(): Promise<void> {
  await fetchApi("/v1/estixe/guardrails/reload", { method: "POST" });
}

// ─── ESTIXE suggestions ───────────────────────────────────────────────────────

export async function getSuggestions(): Promise<SuggestionsResponse> {
  return fetchApi("/v1/estixe/suggestions");
}

export async function approveSuggestion(
  suggestionId: string,
  body?: { intent_name?: string; response?: string },
): Promise<SuggestionApprovalResponse> {
  return fetchApi(`/v1/estixe/suggestions/${suggestionId}/approve`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export async function rejectSuggestion(suggestionId: string): Promise<{ status: string }> {
  return fetchApi(`/v1/estixe/suggestions/${suggestionId}/reject`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ─── Calibration / Shadow mode ────────────────────────────────────────────────

export async function getCalibration(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/calibration/${_activeTenant}`);
}

export async function getCalibrationHistory(): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown> | Record<string, unknown>[]>(
    `/v1/calibration/${_activeTenant}/history`,
  );
  return Array.isArray(raw) ? raw : [raw];
}

export async function promoteCalibration(
  category: string,
  new_threshold: number,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/calibration/${_activeTenant}/promote`, {
    method: "POST",
    body: JSON.stringify({ category, new_threshold }),
  });
}

export async function rollbackCalibration(category: string): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/calibration/${_activeTenant}/rollback`, {
    method: "POST",
    body: JSON.stringify({ category }),
  });
}

// ─── Sessions ─────────────────────────────────────────────────────────────────

export async function getSessions(limit = 50): Promise<Session[]> {
  const raw = await fetchApi<unknown>(`/v1/sessions/${_activeTenant}?limit=${limit}`);
  // Backend may return { sessions: [...] } or [...] directly
  const items = Array.isArray(raw)
    ? raw
    : Array.isArray((raw as Record<string, unknown>).sessions)
    ? (raw as { sessions: unknown[] }).sessions
    : [];
  return items as Session[];
}

export async function getSessionAudit(sessionId: string): Promise<Session> {
  const raw = await fetchApi<Record<string, unknown>>(
    `/v1/session/${sessionId}/audit`,
  );
  // Map backend SessionRecord → frontend Session
  return {
    id: (raw.session_id as string) ?? sessionId,
    user_hash: sessionId.slice(0, 16),
    tenant: (raw.tenant as string) ?? _activeTenant,
    turns: Array.isArray(raw.turns) ? raw.turns.length : 0,
    risk: "low",
    spend: 0,
    outcome: "bypassed",
    hmac_valid: Boolean(raw.hmac_signature),
    started_at: typeof raw.started_at === "number"
      ? new Date((raw.started_at as number) * 1000).toISOString()
      : String(raw.started_at ?? ""),
    last_activity: typeof raw.last_activity === "number"
      ? new Date((raw.last_activity as number) * 1000).toISOString()
      : String(raw.last_activity ?? ""),
    turn_history: [],
  };
}

// ─── Budget / Economics ───────────────────────────────────────────────────────

export async function getBudgetStatus(): Promise<BudgetSummary> {
  const raw = await fetchApi<RawBudgetStatus>(`/v1/budget/${_activeTenant}/status`);
  // Try to get economics data for avoided_cost
  let avoided = 0;
  try {
    const eco = await fetchApi<Record<string, unknown>>("/v1/economics");
    avoided = (eco.total_spend_avoided as number) ?? 0;
  } catch {
    // economics endpoint is optional
  }
  return transformBudgetStatus(raw, avoided);
}

export async function setBudgetCap(config: {
  daily_cap?: number;
  monthly_cap?: number;
  on_cap_reached?: "block" | "downgrade";
  alert_threshold?: number;
}): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/budget/${_activeTenant}`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function getEconomics(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/economics");
}

// ─── Benchmark & Recommendations (NEMOS) ─────────────────────────────────────

export async function getBenchmark(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/benchmark/${_activeTenant}`);
}

export async function getRecommendations(): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown> | Record<string, unknown>[]>(
    `/v1/recommendations/${_activeTenant}`,
  );
  return Array.isArray(raw) ? raw : [];
}

// ─── Intelligence (NEMOS Dashboard) ──────────────────────────────────────────

export async function getIntelligenceOverview(days = 30): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/intelligence/${_activeTenant}/overview?days=${days}`);
}

export async function getIntelligenceIntents(): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown> | Record<string, unknown>[]>(
    `/v1/intelligence/${_activeTenant}/intents`,
  );
  return Array.isArray(raw) ? raw : [];
}

export async function getComplianceSummary(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/intelligence/${_activeTenant}/compliance-summary`);
}

// ─── Threats ──────────────────────────────────────────────────────────────────

export async function getThreats(): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown>[]>(`/v1/threats/${_activeTenant}`);
  return Array.isArray(raw) ? raw : [];
}

// ─── Approvals (Human-in-the-loop) ───────────────────────────────────────────

export async function getApprovals(status?: string): Promise<Record<string, unknown>[]> {
  const qs = status ? `?status=${status}` : "";
  const raw = await fetchApi<Record<string, unknown> | Record<string, unknown>[]>(
    `/v1/approvals${qs}`,
  );
  return Array.isArray(raw)
    ? raw
    : Array.isArray((raw as Record<string, unknown>).approvals)
    ? (raw as { approvals: Record<string, unknown>[] }).approvals
    : [];
}

export async function resolveApproval(
  approvalId: string,
  status: "approved" | "denied",
  approver: string,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/approvals/${approvalId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ status, approver }),
  });
}

// ─── Audit log ────────────────────────────────────────────────────────────────

export async function getAudit(limit = 50): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown>[]>(`/v1/audit?limit=${limit}`);
  return Array.isArray(raw) ? raw : [];
}

// ─── Cache stats ──────────────────────────────────────────────────────────────

export async function getCacheStats(): Promise<CacheStats> {
  return fetchApi("/v1/cache/stats");
}

// ─── Admin ────────────────────────────────────────────────────────────────────

export async function rotateKeys(
  newKeys: string[],
): Promise<{ rotated: boolean; old_keys_revoked_at: number }> {
  return fetchApi("/v1/admin/rotate-keys", {
    method: "POST",
    body: JSON.stringify({ new_keys: newKeys }),
  });
}

// ─── Reports ─────────────────────────────────────────────────────────────────

export async function getExecutiveReport(
  format: "json" | "pdf" = "json",
  days = 30,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/reports/${_activeTenant}/executive?format=${format}&days=${days}`);
}

export async function getReportSchedule(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/reports/${_activeTenant}/schedule`);
}

export async function scheduleReport(config: {
  frequency: "daily" | "weekly" | "monthly";
  recipients: string[];
}): Promise<void> {
  await fetchApi(`/v1/reports/${_activeTenant}/schedule`, {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function deleteReportSchedule(): Promise<void> {
  await fetchApi(`/v1/reports/${_activeTenant}/schedule`, { method: "DELETE" });
}

// ─── Explainability ───────────────────────────────────────────────────────────

export async function explainRequest(requestId: string): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/explain/${requestId}`);
}

// ─── LGPD / Data Deletion ─────────────────────────────────────────────────────

export async function deleteTenantData(tenant: string): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/data/${tenant}`, { method: "DELETE" });
}
