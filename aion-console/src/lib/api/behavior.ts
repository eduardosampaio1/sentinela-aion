import type { BehaviorDial, ModelInfo } from "@/lib/types";
import { fetchApi } from "./_core";

// ─── Behavior dials ───────────────────────────────────────────────────────────

const DEFAULT_DIAL: BehaviorDial = {
  objectivity: 50,
  verbosity: 50,
  economy: 50,
  explanation: 50,
  confidence: 50,
  safe_mode: 50,
  formality: 50,
};

interface BehaviorEnvelope {
  tenant: string;
  behavior: BehaviorDial | null;
  status?: string;
}

/**
 * Fetch the current tenant's behavior dial. Backend wraps the dial in a
 * `{tenant, behavior}` envelope and may return `behavior: null` when the
 * tenant has never set anything — we normalize to a populated `BehaviorDial`
 * so callers don't have to handle the envelope.
 */
export async function getBehavior(): Promise<BehaviorDial> {
  const env = await fetchApi<BehaviorEnvelope>("/v1/behavior");
  return env.behavior ?? DEFAULT_DIAL;
}

/**
 * Update the tenant's behavior dial. Only the fields you pass are changed —
 * the backend merges with the previous config (see C2 fix). Returns the
 * full updated dial after the merge.
 */
export async function setBehavior(dial: Partial<BehaviorDial>): Promise<BehaviorDial> {
  const env = await fetchApi<BehaviorEnvelope>("/v1/behavior", {
    method: "PUT",
    body: JSON.stringify(dial),
  });
  return env.behavior ?? DEFAULT_DIAL;
}

export async function resetBehavior(): Promise<void> {
  await fetchApi("/v1/behavior", { method: "DELETE" });
}

// ─── Models & routing ─────────────────────────────────────────────────────────

/**
 * Validates the *minimum* shape the routing UI needs to render without
 * crashing on property access. Only `id` and `provider` are required —
 * every other field is optional in `ModelInfo` (the JSX uses `?.` and
 * `?? []` to handle absence). This used to require `capabilities`, but
 * that filtered out backend payloads that didn't include it (every model
 * disappeared) — see C1 fix in qa-evidence/console-backend-integration.
 */
function isModelInfoLike(x: unknown): x is ModelInfo {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    o.id.length > 0 &&
    typeof o.provider === "string"
  );
}

export async function getModels(): Promise<ModelInfo[]> {
  // Backend shape varies across versions:
  //   v0.1.0+        → { models: [...] }
  //   future / mock  → [...] (array root)
  //   single-model   → { ... } (rare)
  //   error envelope → { error: ..., code: ... }   ← discard
  //   garbage        → null, "string", true, ...    ← discard
  //
  // We accept all "good" shapes and discard anything that doesn't match the
  // minimum ModelInfo contract. If nothing passes, return [] so the UI shows
  // the empty state cleanly instead of crashing on `.capabilities.map(...)`.
  let raw: unknown;
  try {
    raw = await fetchApi<unknown>("/v1/models");
  } catch {
    return [];
  }

  // Pull a candidate array out of any of the supported envelopes.
  let candidates: unknown[];
  if (Array.isArray(raw)) {
    candidates = raw;
  } else if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    if (Array.isArray(obj.models)) {
      candidates = obj.models;
    } else if (isModelInfoLike(obj)) {
      candidates = [obj];
    } else {
      // Error envelope, status object, anything else — no usable data.
      return [];
    }
  } else {
    return [];
  }

  return candidates.filter(isModelInfoLike);
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
