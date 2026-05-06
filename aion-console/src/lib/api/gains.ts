import { fetchApi } from "./_core";
import type { GainReport } from "@/lib/types";

export async function getGainReport(params?: {
  from?: string;
  to?: string;
  group_by?: string;
}): Promise<GainReport> {
  const qs = new URLSearchParams();
  if (params?.from) qs.set("from", params.from);
  if (params?.to) qs.set("to", params.to);
  if (params?.group_by) qs.set("group_by", params.group_by);
  const query = qs.toString();
  // Tenant is resolved server-side from X-Aion-Tenant header (injected by fetchApi/_core)
  return fetchApi<GainReport>(`/v1/nemos/gain${query ? `?${query}` : ""}`);
}
