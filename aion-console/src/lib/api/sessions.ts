import type { Session } from "@/lib/types";
import { fetchApi, getActiveTenant } from "./_core";

export async function getSessions(limit = 50): Promise<Session[]> {
  const raw = await fetchApi<unknown>(`/v1/sessions/${getActiveTenant()}?limit=${limit}`);
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
  return {
    id: (raw.session_id as string) ?? sessionId,
    user_hash: sessionId.slice(0, 16),
    tenant: (raw.tenant as string) ?? getActiveTenant(),
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
