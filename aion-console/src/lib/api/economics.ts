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
