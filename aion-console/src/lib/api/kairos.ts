/**
 * KAIROS API client — Policy Lifecycle Manager.
 *
 * All requests flow through /api/proxy which injects Authorization and
 * forwards X-Aion-Tenant. Approve/reject send reason in the JSON body
 * (required by backend) and also in X-Aion-Actor-Reason header (proxy audit).
 * The header value is URI-encoded to avoid HTTP header encoding issues with
 * non-ASCII characters (e.g. Portuguese accents).
 */
import { fetchApi } from "./_core";

// ── Types ──────────────────────────────────────────────────────────────────

export type PolicyTemplate = {
  id: string;
  vertical: string;
  type: string;
  title: string;
  description?: string;
};

export type PolicyCandidateStatus =
  | "draft"
  | "ready_for_shadow"
  | "shadow_running"
  | "shadow_completed"
  | "approved_production"
  | "under_review"
  | "rejected"
  | "deprecated"
  | "archived";

export type PolicyCandidate = {
  id: string;
  tenant_id: string;
  template_id: string | null;
  type: string;
  status: PolicyCandidateStatus;
  title: string;
  business_summary: string;
  technical_summary: string;
  trigger_conditions: Array<{ field: string; operator: string; value: unknown }>;
  proposed_actions: unknown[];
  created_at: string;
  updated_at: string;
  shadow_run_id: string | null;
  approved_by: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
};

export type ShadowRunSummary = {
  observations: number;
  matched: number;
  fallback: number;
  match_rate: number;
  fallback_rate: number;
};

export type ShadowRun = {
  id: string;
  status: "running" | "completed" | "failed";
  observations_count: number;
  matched_count: number;
  fallback_count: number;
  started_at: string;
  completed_at: string | null;
  summary: ShadowRunSummary | null;
};

export type LifecycleEvent = {
  id: string;
  candidate_id: string;
  from_status: string | null;
  to_status: string;
  actor_type: string;
  actor_id: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type CandidateDetail = PolicyCandidate & {
  lifecycle_events: LifecycleEvent[];
  shadow_run: ShadowRun | null;
};

// ── Raw response shapes (backend envelope) ────────────────────────────────

type RawTemplatesResponse = { templates: PolicyTemplate[]; count: number };
type RawCandidatesResponse = { candidates: PolicyCandidate[]; count: number };
type RawCandidateDetailResponse = {
  candidate: PolicyCandidate;
  lifecycle_events: LifecycleEvent[];
  shadow_run: ShadowRun | null;
};
type RawShadowStartResponse = {
  candidate: PolicyCandidate;
  shadow_run: ShadowRun;
};

// ── API functions ──────────────────────────────────────────────────────────

export async function getKairosTemplates(): Promise<PolicyTemplate[]> {
  const raw = await fetchApi<RawTemplatesResponse>("/v1/kairos/templates");
  return raw.templates;
}

export async function getKairosCandidates(status?: string): Promise<PolicyCandidate[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const raw = await fetchApi<RawCandidatesResponse>(`/v1/kairos/candidates${qs}`);
  return raw.candidates;
}

export async function getKairosCandidate(id: string): Promise<CandidateDetail> {
  const raw = await fetchApi<RawCandidateDetailResponse>(
    `/v1/kairos/candidates/${encodeURIComponent(id)}`,
  );
  return {
    ...raw.candidate,
    lifecycle_events: raw.lifecycle_events,
    shadow_run: raw.shadow_run,
  };
}

export async function createCandidateFromTemplate(templateId: string): Promise<PolicyCandidate> {
  return fetchApi<PolicyCandidate>("/v1/kairos/candidates/from-template", {
    method: "POST",
    body: JSON.stringify({ template_id: templateId }),
  });
}

export async function markCandidateReady(id: string): Promise<PolicyCandidate> {
  return fetchApi<PolicyCandidate>(
    `/v1/kairos/candidates/${encodeURIComponent(id)}/ready`,
    { method: "POST" },
  );
}

export async function startKairosShadow(id: string): Promise<PolicyCandidate> {
  const raw = await fetchApi<RawShadowStartResponse>(
    `/v1/kairos/candidates/${encodeURIComponent(id)}/shadow`,
    { method: "POST" },
  );
  return raw.candidate;
}

export async function approveKairosCandidate(id: string, reason: string): Promise<PolicyCandidate> {
  return fetchApi<PolicyCandidate>(
    `/v1/kairos/candidates/${encodeURIComponent(id)}/approve`,
    {
      method: "POST",
      // reason in body (read by backend) + header (proxy audit trail, URI-encoded for safety)
      headers: { "X-Aion-Actor-Reason": encodeURIComponent(reason) },
      body: JSON.stringify({ reason }),
    },
  );
}

export async function rejectKairosCandidate(id: string, reason: string): Promise<PolicyCandidate> {
  return fetchApi<PolicyCandidate>(
    `/v1/kairos/candidates/${encodeURIComponent(id)}/reject`,
    {
      method: "POST",
      // reason in body (REQUIRED by backend) + header (proxy audit trail, URI-encoded for safety)
      headers: { "X-Aion-Actor-Reason": encodeURIComponent(reason) },
      body: JSON.stringify({ reason }),
    },
  );
}
