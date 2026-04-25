import type { Session, SessionTurn } from "@/lib/types";
import { fetchApi, getActiveTenant } from "./_core";

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Derive session-level risk label from max risk_score across turns. */
function riskFromScore(score: number): Session["risk"] {
  if (score < 0.3) return "low";
  if (score < 0.6) return "medium";
  if (score < 0.8) return "high";
  return "critical";
}

/** Map backend decision string to frontend Session outcome. */
const DECISION_TO_OUTCOME: Record<string, Session["outcome"]> = {
  bypass: "bypassed",
  continue: "routed",
  route: "routed",
  block: "blocked",
  fallback: "routed",
};

// ─── getSessions ──────────────────────────────────────────────────────────────

/**
 * List sessions for the active tenant.
 *
 * Backend returns: { tenant, page, sessions: [{ session_id, last_activity }] }
 * The session list is intentionally minimal (LGPD). Derived fields (risk, outcome,
 * spend, hmac_valid, turn_history) are populated lazily via getSessionAudit().
 */
export async function getSessions(limit = 50): Promise<Session[]> {
  const raw = await fetchApi<unknown>(`/v1/sessions/${getActiveTenant()}?limit=${limit}`);
  const data = raw as Record<string, unknown>;

  // Backend may return array directly OR wrapped in { sessions: [...] }
  const items: Record<string, unknown>[] = Array.isArray(raw)
    ? (raw as Record<string, unknown>[])
    : Array.isArray(data.sessions)
    ? (data.sessions as Record<string, unknown>[])
    : [];

  return items.map((item) => {
    const sessionId = String(item.session_id ?? item.id ?? "");
    return {
      id: sessionId,
      // LGPD: show only 8-char prefix of session_id as user identifier
      user_hash: sessionId.slice(0, 8),
      tenant: String(item.tenant ?? getActiveTenant()),
      turns: typeof item.turns_count === "number" ? (item.turns_count as number) : 0,
      started_at:
        typeof item.started_at === "number"
          ? new Date((item.started_at as number) * 1000).toISOString()
          : String(item.started_at ?? ""),
      last_activity:
        typeof item.last_activity === "number"
          ? new Date((item.last_activity as number) * 1000).toISOString()
          : String(item.last_activity ?? ""),
      // Derived fields: undefined until getSessionAudit() is called for this session
      risk: undefined,
      spend: undefined,
      outcome: undefined,
      hmac_valid: undefined,
      turn_history: undefined,
    };
  });
}

// ─── getSessionAudit ──────────────────────────────────────────────────────────

/**
 * Fetch full audit trail for a session.
 *
 * Backend TurnAuditEntry fields:
 *   request_id, timestamp, timestamp_iso, user_message_hash (SHA256, LGPD),
 *   decision, model_used, pii_types_detected, risk_score, intent_detected,
 *   policies_matched, tokens_sent, tokens_received, latency_ms
 *
 * Derived session-level fields:
 *   risk     = riskFromScore(max risk_score across turns)
 *   outcome  = DECISION_TO_OUTCOME[last turn decision]
 *   hmac_valid = raw.verified (backend verifies HMAC-SHA256)
 *   spend    = undefined (no USD cost in TurnAuditEntry — add when backend exposes it)
 */
export async function getSessionAudit(sessionId: string): Promise<Session> {
  const raw = await fetchApi<Record<string, unknown>>(
    `/v1/session/${sessionId}/audit`,
  );

  const rawTurns = Array.isArray(raw.turns)
    ? (raw.turns as Record<string, unknown>[])
    : [];

  const turns: SessionTurn[] = rawTurns.map((t, idx) => {
    // Normalize decision → frontend union
    const rawDecision = String(t.decision ?? "");
    const decision: SessionTurn["decision"] =
      rawDecision === "bypass"
        ? "bypass"
        : rawDecision === "block"
        ? "block"
        : rawDecision === "fallback"
        ? "fallback"
        : "route";

    // LGPD: user_message_hash is a 16-char sha256 prefix — display as "[hash…]"
    const hash = String(t.user_message_hash ?? "");
    const input = hash ? `[${hash}…]` : "[mensagem anonimizada]";

    return {
      turn: idx + 1,
      timestamp:
        typeof t.timestamp_iso === "string"
          ? t.timestamp_iso
          : typeof t.timestamp === "number"
          ? new Date((t.timestamp as number) * 1000).toISOString()
          : new Date().toISOString(),
      input,
      decision,
      // backend does not expose which module handled the turn per-entry
      module: null,
      model_used: typeof t.model_used === "string" ? t.model_used : null,
      latency_ms:
        typeof t.latency_ms === "number" ? Math.round(t.latency_ms as number) : 0,
      // cost: not available from TurnAuditEntry (no USD per-turn cost stored)
      cost: undefined,
      risk_score: typeof t.risk_score === "number" ? (t.risk_score as number) : 0,
      pii_detected: Array.isArray(t.pii_types_detected)
        ? (t.pii_types_detected as string[])
        : [],
      // metis_compressed: not tracked per-turn in the current audit schema
      metis_compressed: false,
    };
  });

  // ── Derive session-level summary from turns ──
  const maxRisk = turns.reduce((m, t) => Math.max(m, t.risk_score), 0);
  const lastDecision = turns.length > 0 ? turns[turns.length - 1].decision : "route";

  return {
    id: typeof raw.session_id === "string" ? raw.session_id : sessionId,
    // LGPD: use 8-char prefix of session_id as user identifier
    user_hash: sessionId.slice(0, 8),
    tenant: typeof raw.tenant === "string" ? raw.tenant : getActiveTenant(),
    turns: rawTurns.length,
    risk: riskFromScore(maxRisk),
    spend: undefined, // add when backend exposes per-session cost
    outcome: DECISION_TO_OUTCOME[lastDecision] ?? "routed",
    // verified = backend HMAC-SHA256 check result
    hmac_valid: Boolean(raw.verified),
    started_at:
      typeof raw.started_at_iso === "string"
        ? raw.started_at_iso
        : typeof raw.started_at === "number"
        ? new Date((raw.started_at as number) * 1000).toISOString()
        : "",
    last_activity:
      typeof raw.last_activity_iso === "string"
        ? raw.last_activity_iso
        : typeof raw.last_activity === "number"
        ? new Date((raw.last_activity as number) * 1000).toISOString()
        : "",
    turn_history: turns,
  };
}
