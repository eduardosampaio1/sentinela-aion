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
  BudgetCap,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_AION_API_URL || "http://localhost:8080";

let _activeTenant = "default";

export function setActiveTenant(tenant: string) {
  _activeTenant = tenant;
}

export function getActiveTenant(): string {
  return _activeTenant;
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      "X-Aion-Tenant": _activeTenant,
      ...options?.headers,
    },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`AION API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// Health
export async function getHealth(): Promise<{ status: string }> {
  return fetchApi("/health");
}

// Stats
export async function getStats(): Promise<Stats> {
  return fetchApi("/v1/stats");
}

// Events
export async function getEvents(limit = 50): Promise<AionEvent[]> {
  return fetchApi(`/v1/events?limit=${limit}`);
}

// Behavior
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

// Models
export async function getModels(): Promise<ModelInfo[]> {
  return fetchApi("/v1/models");
}

// Reload
export async function reloadIntents(): Promise<void> {
  await fetchApi("/v1/estixe/intents/reload", { method: "POST" });
}

export async function reloadPolicies(): Promise<void> {
  await fetchApi("/v1/estixe/policies/reload", { method: "POST" });
}

// Economics
export async function getEconomics(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/economics");
}

// Killswitch
export async function getKillswitch(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/killswitch");
}

// Audit
export async function getAudit(limit = 50): Promise<Record<string, unknown>[]> {
  return fetchApi(`/v1/audit?limit=${limit}`);
}

// Cache stats
export async function getCacheStats(): Promise<CacheStats> {
  return fetchApi("/v1/cache/stats");
}

// Intent suggestions (auto-discovery)
export async function getSuggestions(): Promise<SuggestionsResponse> {
  return fetchApi("/v1/estixe/suggestions");
}

export async function approveSuggestion(
  suggestionId: string,
  body?: { intent_name?: string; response?: string },
): Promise<SuggestionApprovalResponse> {
  return fetchApi(`/v1/estixe/suggestions/${suggestionId}/approve`, {
    method: "POST",
    body: JSON.stringify(body || {}),
  });
}

export async function rejectSuggestion(suggestionId: string): Promise<{ status: string }> {
  return fetchApi(`/v1/estixe/suggestions/${suggestionId}/reject`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// Overrides
export async function getOverrides(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/overrides");
}

export async function setOverrides(overrides: Record<string, unknown>): Promise<Record<string, unknown>> {
  return fetchApi("/v1/overrides", {
    method: "PUT",
    body: JSON.stringify(overrides),
  });
}

// Sessions
export async function getSessions(limit = 50): Promise<Session[]> {
  return fetchApi(`/v1/sessions/${_activeTenant}?limit=${limit}`);
}

export async function getSessionAudit(sessionId: string): Promise<Session> {
  return fetchApi(`/v1/session/${sessionId}/audit`);
}

// Budget
export async function getBudgetStatus(): Promise<BudgetSummary> {
  return fetchApi(`/v1/budget/${_activeTenant}/status`);
}

export async function setBudgetCap(cap: Partial<BudgetCap> & { department: string }): Promise<BudgetCap> {
  return fetchApi(`/v1/budget/${_activeTenant}`, {
    method: "PUT",
    body: JSON.stringify(cap),
  });
}

// Shadow mode
export async function getShadowConfig(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/shadow/config");
}

export async function getShadowResults(limit = 50): Promise<Record<string, unknown>[]> {
  return fetchApi(`/v1/shadow/results?limit=${limit}`);
}

// Threats
export async function getThreats(): Promise<Record<string, unknown>[]> {
  return fetchApi(`/v1/threats/${_activeTenant}`);
}

// Intelligence (NEMOS)
export async function getIntelligenceOverview(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/intelligence/${_activeTenant}/overview`);
}

// Reports
export async function getExecutiveReport(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/reports/${_activeTenant}/executive`);
}

export async function scheduleReport(config: { frequency: string; format: string }): Promise<void> {
  await fetchApi(`/v1/reports/${_activeTenant}/schedule`, {
    method: "POST",
    body: JSON.stringify(config),
  });
}
