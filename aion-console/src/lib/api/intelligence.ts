import { fetchApi, getActiveTenant } from "./_core";

export async function getBenchmark(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/benchmark/${getActiveTenant()}`);
}

export async function getRecommendations(): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown> | Record<string, unknown>[]>(
    `/v1/recommendations/${getActiveTenant()}`,
  );
  return Array.isArray(raw) ? raw : [];
}

export async function getIntelligenceOverview(days = 30): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/intelligence/${getActiveTenant()}/overview?days=${days}`);
}

export async function getIntelligenceIntents(): Promise<Record<string, unknown>[]> {
  // Backend returns { tenant, count, intents: [...] }
  const raw = await fetchApi<Record<string, unknown>>(
    `/v1/intelligence/${getActiveTenant()}/intents`,
  );
  // Support both array (future) and envelope { intents: [...] } formats
  if (Array.isArray(raw)) return raw as Record<string, unknown>[];
  if (Array.isArray(raw.intents)) return raw.intents as Record<string, unknown>[];
  return [];
}

export async function getComplianceSummary(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/intelligence/${getActiveTenant()}/compliance-summary`);
}

export async function getGlobalThreatFeed(
  category?: string,
  limit = 20,
): Promise<Record<string, unknown>[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (category) qs.set("category", category);
  const raw = await fetchApi<Record<string, unknown>>(
    `/v1/global/threat-feed/${getActiveTenant()}?${qs}`,
  );
  if (Array.isArray(raw)) return raw as Record<string, unknown>[];
  const items = (raw as Record<string, unknown>).signals;
  return Array.isArray(items) ? (items as Record<string, unknown>[]) : [];
}
