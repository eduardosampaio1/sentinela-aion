import { fetchApi, getActiveTenant } from "./_core";

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
): Promise<{ rotated: boolean; old_keys_revoked_at: number }> {
  return fetchApi("/v1/admin/rotate-keys", {
    method: "POST",
    body: JSON.stringify({ new_keys: newKeys }),
  });
}

// ─── LGPD / Data deletion ─────────────────────────────────────────────────────

export async function deleteTenantData(tenant: string): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/data/${tenant}`, { method: "DELETE" });
}

// ─── Tenant settings ──────────────────────────────────────────────────────────

export async function getTenantSettings(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/tenant/${getActiveTenant()}/settings`);
}

export async function updateTenantSettings(
  settings: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/tenant/${getActiveTenant()}/settings`, {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}
