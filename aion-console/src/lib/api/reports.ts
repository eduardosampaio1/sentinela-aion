import { fetchApi, getActiveTenant } from "./_core";

export async function getExecutiveReport(
  format: "json" | "pdf" = "json",
  days = 30,
): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/reports/${getActiveTenant()}/executive?format=${format}&days=${days}`);
}

export async function getReportSchedule(): Promise<Record<string, unknown>> {
  return fetchApi(`/v1/reports/${getActiveTenant()}/schedule`);
}

export async function scheduleReport(config: {
  frequency: "daily" | "weekly" | "monthly";
  recipients: string[];
}): Promise<void> {
  await fetchApi(`/v1/reports/${getActiveTenant()}/schedule`, {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function deleteReportSchedule(): Promise<void> {
  await fetchApi(`/v1/reports/${getActiveTenant()}/schedule`, { method: "DELETE" });
}
