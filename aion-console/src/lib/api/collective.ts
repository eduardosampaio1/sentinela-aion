import type { CollectivePolicy, InstalledCollectivePolicy } from "@/lib/types";
import { fetchApi, getActiveTenant } from "./_core";

interface BrowseResponse {
  count: number;
  phase: string;
  policies: CollectivePolicy[];
}

interface InstalledResponse {
  tenant: string;
  count: number;
  installed: InstalledCollectivePolicy[];
}

interface InstallResponse {
  status: "sandbox" | "shadow" | "production";
  policy_id: string;
  tenant: string;
  installed_at: number;
  message: string;
}

export async function browseCollectivePolicies(sector?: string): Promise<CollectivePolicy[]> {
  const qs = sector ? `?sector=${encodeURIComponent(sector)}` : "";
  const data = await fetchApi<BrowseResponse>(`/v1/collective/policies${qs}`);
  return data.policies ?? [];
}

export async function getCollectivePolicy(id: string): Promise<CollectivePolicy> {
  return fetchApi<CollectivePolicy>(`/v1/collective/policies/${id}`);
}

export async function getInstalledPolicies(
  tenant?: string,
): Promise<InstalledCollectivePolicy[]> {
  const t = tenant ?? getActiveTenant();
  const data = await fetchApi<InstalledResponse>(`/v1/collective/installed/${t}`);
  return data.installed ?? [];
}

export async function installCollectivePolicy(
  policyId: string,
  reason: string,
): Promise<InstallResponse> {
  return fetchApi<InstallResponse>(`/v1/collective/policies/${policyId}/install`, {
    method: "POST",
    headers: { "X-Aion-Actor-Reason": reason },
  });
}

export async function promoteCollectivePolicy(
  policyId: string,
  reason: string,
): Promise<Record<string, unknown>> {
  return fetchApi<Record<string, unknown>>(
    `/v1/collective/policies/${policyId}/promote`,
    {
      method: "PUT",
      headers: { "X-Aion-Actor-Reason": reason },
      body: JSON.stringify({ tenant: getActiveTenant() }),
    },
  );
}
