import { fetchApi } from "./_core";

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

// ─── Key rotation ─────────────────────────────────────────────────────────────

export async function rotateKeys(
  newKeys: string[],
  /** Required when using console_proxy service key — backend returns 400 if absent. */
  reason?: string,
): Promise<{ rotated: boolean; old_keys_revoked_at: number }> {
  return fetchApi("/v1/admin/rotate-keys", {
    method: "POST",
    body: JSON.stringify({ new_keys: newKeys }),
    ...(reason ? { headers: { "X-Aion-Actor-Reason": reason } } : {}),
  });
}

// ─── LGPD / Data deletion ─────────────────────────────────────────────────────

export async function deleteTenantData(
  tenant: string,
  /** Required when using console_proxy service key — backend returns 400 if absent. */
  reason?: string,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/data/${tenant}`, {
    method: "DELETE",
    ...(reason ? { headers: { "X-Aion-Actor-Reason": reason } } : {}),
  });
}

// ─── Tenant settings ──────────────────────────────────────────────────────────
// Removed in M1 fix: getTenantSettings / updateTenantSettings were dead code.
// The backend never had GET/PUT /v1/tenant/{tenant}/settings, no component in
// the console called these helpers. Kept this comment as a tombstone so a
// future reviewer doesn't add the same broken pair back.
