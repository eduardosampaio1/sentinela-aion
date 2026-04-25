import { fetchApi, getActiveTenant } from "./_core";

export async function browseMarketplace(
  params: { category?: string; tag?: string; limit?: number } = {},
): Promise<Record<string, unknown>[]> {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.tag) qs.set("tag", params.tag);
  if (params.limit) qs.set("limit", String(params.limit));
  const raw = await fetchApi<Record<string, unknown> | Record<string, unknown>[]>(
    `/v1/marketplace/policies${qs.toString() ? `?${qs}` : ""}`,
  );
  if (Array.isArray(raw)) return raw;
  const arr = (raw as Record<string, unknown>).policies;
  return Array.isArray(arr) ? (arr as Record<string, unknown>[]) : [];
}

export async function getMarketplacePolicy(policyId: string): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/marketplace/policies/${policyId}`);
}

export async function installMarketplacePolicy(
  policyId: string,
  shadow = true,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/marketplace/policies/${policyId}/install`, {
    method: "POST",
    body: JSON.stringify({ tenant: getActiveTenant(), shadow_mode: shadow }),
  });
}

export async function rateMarketplacePolicy(
  policyId: string,
  rating: number,
  comment = "",
): Promise<void> {
  await fetchApi(`/v1/marketplace/policies/${policyId}/rate`, {
    method: "POST",
    body: JSON.stringify({ tenant: getActiveTenant(), rating, comment }),
  });
}
