import type { SuggestionsResponse, SuggestionApprovalResponse } from "@/lib/types";
import { fetchApi, getActiveTenant } from "./_core";

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
  return fetchApi(`/v1/calibration/${getActiveTenant()}`);
}

export async function getCalibrationHistory(): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown> | Record<string, unknown>[]>(
    `/v1/calibration/${getActiveTenant()}/history`,
  );
  return Array.isArray(raw) ? raw : [raw];
}

export async function promoteCalibration(
  category: string,
  new_threshold: number,
  /** Required when using console_proxy service key — backend returns 400 if absent. */
  reason?: string,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/calibration/${getActiveTenant()}/promote`, {
    method: "POST",
    body: JSON.stringify({ category, new_threshold }),
    ...(reason ? { headers: { "X-Aion-Actor-Reason": reason } } : {}),
  });
}

export async function rollbackCalibration(
  category: string,
  /** Required when using console_proxy service key — backend returns 400 if absent. */
  reason?: string,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/calibration/${getActiveTenant()}/rollback`, {
    method: "POST",
    body: JSON.stringify({ category }),
    ...(reason ? { headers: { "X-Aion-Actor-Reason": reason } } : {}),
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
    // reason goes both in the body (for the killswitch record) and as header (for the audit trail)
    headers: { "X-Aion-Actor-Reason": reason },
  });
}

export async function deactivateKillswitch(
  /** Required when using console_proxy service key — backend returns 400 if absent. */
  reason?: string,
): Promise<{ killswitch_active: false }> {
  return fetchApi("/v1/killswitch", {
    method: "DELETE",
    ...(reason ? { headers: { "X-Aion-Actor-Reason": reason } } : {}),
  });
}

// ─── Threats ──────────────────────────────────────────────────────────────────

export async function getThreats(): Promise<Record<string, unknown>[]> {
  const raw = await fetchApi<Record<string, unknown>[]>(`/v1/threats/${getActiveTenant()}`);
  return Array.isArray(raw) ? raw : [];
}
