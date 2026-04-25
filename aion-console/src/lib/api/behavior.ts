import type { BehaviorDial, ModelInfo } from "@/lib/types";
import { fetchApi } from "./_core";

// ─── Behavior dials ───────────────────────────────────────────────────────────

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

// ─── Models & routing ─────────────────────────────────────────────────────────

export async function getModels(): Promise<ModelInfo[]> {
  const raw = await fetchApi<ModelInfo | ModelInfo[]>("/v1/models");
  return Array.isArray(raw) ? raw : [raw];
}

export async function getPipelineTopology(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/pipeline");
}

export async function toggleModule(
  module: "estixe" | "nomos" | "metis",
  enabled: boolean,
  /** Required when using console_proxy service key — backend returns 400 if absent. */
  reason?: string,
): Promise<{ module: string; enabled: boolean }> {
  return fetchApi(`/v1/modules/${module}/toggle`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
    ...(reason ? { headers: { "X-Aion-Actor-Reason": reason } } : {}),
  });
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

// ─── Hot reload ───────────────────────────────────────────────────────────────

export async function reloadIntents(): Promise<void> {
  await fetchApi("/v1/estixe/intents/reload", { method: "POST" });
}

export async function reloadPolicies(): Promise<void> {
  await fetchApi("/v1/estixe/policies/reload", { method: "POST" });
}

export async function reloadGuardrails(): Promise<void> {
  await fetchApi("/v1/estixe/guardrails/reload", { method: "POST" });
}
