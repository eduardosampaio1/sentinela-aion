import type { Stats, AionEvent, BehaviorDial, ModelInfo } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_AION_API_URL || "http://localhost:8000";

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      "X-Aion-Tenant": "default",
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
