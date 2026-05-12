import type { BudgetSummary } from "@/lib/types";
import { fetchApi, getActiveTenant, transformBudgetStatus } from "./_core";
import type { RawBudgetStatus } from "./_core";

export async function getBudgetStatus(): Promise<BudgetSummary> {
  const raw = await fetchApi<RawBudgetStatus>(`/v1/budget/${getActiveTenant()}/status`);
  let avoided = 0;
  try {
    const eco = await fetchApi<Record<string, unknown>>("/v1/economics");
    avoided = (eco.total_spend_avoided as number) ?? 0;
  } catch {
    // economics endpoint is optional
  }
  return transformBudgetStatus(raw, avoided);
}

export async function setBudgetCap(config: {
  daily_cap?: number;
  monthly_cap?: number;
  on_cap_reached?: "block" | "downgrade";
  alert_threshold?: number;
}): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/budget/${getActiveTenant()}`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function getEconomics(): Promise<Record<string, unknown>> {
  return fetchApi("/v1/economics");
}

export interface DailyEconomicsRow {
  id: string;
  tenant: string;
  date: string;
  total_requests: number;
  total_cost_usd: number;
  total_savings_usd: number;
  bypass_count: number;
  block_count: number;
  tokens_saved: number;
  by_model: Record<string, { requests: number; cost_usd: number }>;
  updated_at: string;
}

export interface DailyEconomicsResponse {
  tenant: string;
  days: number;
  rows: DailyEconomicsRow[];
}

export async function getEconomicsDaily(days = 30): Promise<DailyEconomicsRow[]> {
  try {
    const resp = await fetchApi<DailyEconomicsResponse>(
      `/v1/economics/daily?days=${days}`
    );
    return Array.isArray(resp.rows) ? resp.rows : [];
  } catch {
    return [];
  }
}
