"use client";

import { useState } from "react";
import React from "react";
import {
  FileBarChart,
  Download,
  Clock,
  Shield,
  Wallet,
  FlaskConical,
  ScrollText,
  CheckCircle2,
  TrendingDown,
  AlertTriangle,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/demo-banner";
import { TimeRangeSelect } from "@/components/ui/time-range-select";
import type { TimeRange } from "@/components/ui/time-range-select";
import { mockBudgetSummary, mockThreatCategories, mockIntentPerformance, mockSessions, mockStats } from "@/lib/mock-data";
import { useApiData } from "@/lib/use-api-data";
import { getStats, getBudgetStatus, getSessions, getExecutiveReport, API_BASE, getActiveTenant, getThreats, getReportSchedule, scheduleReport, deleteReportSchedule } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Tab = "exec" | "security" | "costs" | "shadow" | "audit" | "schedule";

const TAB_IDS: Tab[] = ["exec", "security", "costs", "shadow", "audit", "schedule"];

const exportFormats = ["PDF", "PPTX", "CSV", "XLSX"] as const;

function MetricCard({ label, value, sub, accent }: { label: string; value: string; sub: string; accent?: string }) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <p className="text-xs text-[var(--color-text-muted)]">{label}</p>
      <p className={`mt-1.5 text-2xl font-bold ${accent ?? "text-[var(--color-text)]"}`}>{value}</p>
      <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">{sub}</p>
    </div>
  );
}

function getTimeRangeLabel(range: TimeRange): string {
  const labels: Record<TimeRange, string> = {
    live: "últimos 5 minutos",
    "1h": "última hora",
    "4h": "últimas 4 horas",
    "24h": "últimas 24 horas",
    "2d": "últimos 2 dias",
    "7d": "últimos 7 dias",
    "14d": "últimos 14 dias",
    "30d": "últimos 30 dias",
  };
  return labels[range];
}

function getRequestsForRange(range: TimeRange): string {
  const map: Record<TimeRange, string> = {
    live: "2.840",
    "1h": "35.600",
    "4h": "142.400",
    "24h": "847.240",
    "2d": "1.694.480",
    "7d": "5.930.680",
    "14d": "11.861.360",
    "30d": "25.416.240",
  };
  return map[range];
}

function ExecTab({ timeRange }: { timeRange: TimeRange }) {
  const t = useT();
  const { data: stats, isDemo, refetch } = useApiData(getStats, mockStats, { intervalMs: 30_000 });
  const bypassPct = stats.total_requests > 0
    ? ((stats.bypasses / stats.total_requests) * 100).toFixed(1)
    : "68.4";
  const latency = stats.avg_latency_ms > 0 ? `${stats.avg_latency_ms}ms` : "312ms";

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner onRetry={refetch} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Total de requisições" value={getRequestsForRange(timeRange)} sub={getTimeRangeLabel(timeRange)} />
        <MetricCard label="Taxa de bypass" value={`${bypassPct}%`} sub="+4.2pp vs período anterior" accent="text-teal-400" />
        <MetricCard label="Latência p95" value={latency} sub="pipeline completo" />
        <MetricCard label="Uptime" value="99.97%" sub={getTimeRangeLabel(timeRange)} accent="text-green-400" />
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
        <h3 className="mb-4 text-sm font-semibold text-[var(--color-text)]">{t("reports.tabs.performance_header")}</h3>
        <div className="space-y-3">
          {[
            { name: "Proteção", requests: 847240, bypassed: 579710, pct: 68.4, color: "bg-teal-500" },
            { name: "Roteamento", requests: 267530, routed: 241600, pct: 90.3, color: "bg-sky-500" },
            { name: "Otimização", requests: 241600, compressed: 55568, pct: 23.0, color: "bg-violet-500" },
          ].map((m) => (
            <div key={m.name} className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-[var(--color-text)]">{m.name}</span>
                <span className="text-[var(--color-text-muted)]">{m.pct.toFixed(1)}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-white/10">
                <div className={`h-2 rounded-full ${m.color}`} style={{ width: `${m.pct}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const PATTERN_REPORT_LABELS: Record<string, string> = {
  progressive_bypass: "Bypass Progressivo",
  intent_mutation: "Mutação de Intent",
  authority_escalation: "Escalada de Autoridade",
  threshold_probing: "Sondagem de Limiar",
};

function SecurityTab({ timeRange }: { timeRange: TimeRange }) {
  const t = useT();
  const { data: threats, isDemo: threatsIsDemo, refetch: refetchThreats } = useApiData(
    getThreats,
    [] as Record<string, unknown>[],
    { intervalMs: 60_000 },
  );

  const mockTotal = mockThreatCategories.reduce((s, t) => s + t.count, 0);
  const threatScalers: Record<TimeRange, number> = {
    live: 0.05, "1h": 0.5, "4h": 2, "24h": 1, "2d": 2, "7d": 7, "14d": 14, "30d": 30,
  };
  const scale = threatScalers[timeRange] || 1;
  const scaledThreats = Math.round(mockTotal * scale);

  // Group real threats by pattern
  const patternCounts: Record<string, number> = {};
  for (const t of threats) {
    const p = (t.pattern as string) ?? "unknown";
    patternCounts[p] = (patternCounts[p] ?? 0) + 1;
  }
  const totalRealThreats = threats.length;

  return (
    <div className="space-y-6">
      {threatsIsDemo && <DemoBanner onRetry={refetchThreats} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Ameaças ativas agora" value={totalRealThreats.toString()} sub="detector multi-turn" accent="text-red-400" />
        <MetricCard label="Ameaças bloqueadas" value={scaledThreats.toLocaleString("pt-BR")} sub={getTimeRangeLabel(timeRange)} accent="text-orange-400" />
        <MetricCard label="PIIs interceptadas" value={Math.round(1204 * scale).toString()} sub="antes do LLM" accent="text-amber-400" />
        <MetricCard label="Sessões suspeitas" value={Math.round(37 * scale).toString()} sub="threat score > 0.8" />
      </div>

      {/* Real active threats */}
      {totalRealThreats > 0 && (
        <div className="rounded-xl border border-red-800/40 bg-[var(--color-surface)]">
          <div className="border-b border-[var(--color-border)] px-5 py-4">
            <h3 className="text-sm font-semibold text-red-400">{t("reports.tabs.active_threats")}</h3>
          </div>
          <div className="divide-y divide-[var(--color-border)]/50">
            {Object.entries(patternCounts).map(([pattern, count]) => (
              <div key={pattern} className="flex items-center gap-4 px-5 py-3">
                <div className="w-48 shrink-0 text-sm text-[var(--color-text)]">
                  {PATTERN_REPORT_LABELS[pattern] ?? pattern.replace(/_/g, " ")}
                </div>
                <div className="flex-1">
                  <div className="h-1.5 w-full rounded-full bg-white/10">
                    <div
                      className="h-1.5 rounded-full bg-red-500/70"
                      style={{ width: `${(count / totalRealThreats) * 100}%` }}
                    />
                  </div>
                </div>
                <span className="w-8 text-right text-xs font-medium text-red-400">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Mock historical categories */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-5 py-4">
          <h3 className="text-sm font-semibold text-[var(--color-text)]">{t("reports.tabs.historical_threats")}</h3>
        </div>
        <div className="divide-y divide-[var(--color-border)]/50">
          {mockThreatCategories.map((t) => (
            <div key={t.name} className="flex items-center gap-4 px-5 py-3">
              <div className="w-40 shrink-0 text-sm text-[var(--color-text)]">{t.name}</div>
              <div className="flex-1">
                <div className="h-1.5 w-full rounded-full bg-white/10">
                  <div className="h-1.5 rounded-full bg-red-500/70" style={{ width: `${t.pct}%` }} />
                </div>
              </div>
              <span className="w-12 text-right text-xs font-medium text-[var(--color-text-muted)]">{t.count}</span>
              <Badge variant={t.action === "block" ? "error" : t.action === "sanitize" ? "warning" : "muted"}>
                {t.action}
              </Badge>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CostsTab({ timeRange }: { timeRange: TimeRange }) {
  const t = useT();
  const { data: budget, isDemo, refetch } = useApiData(getBudgetStatus, mockBudgetSummary, { intervalMs: 60_000 });
  const costScalers: Record<TimeRange, number> = {
    live: 0.05, "1h": 0.5, "4h": 2, "24h": 1, "2d": 2, "7d": 7, "14d": 14, "30d": 30,
  };
  const scale = costScalers[timeRange] || 1;
  const scaledSpent = (budget.used_usd * scale).toFixed(2);
  const scaledAvoided = (budget.avoided_cost * scale).toFixed(2);
  const roi = budget.avoided_cost > 0 && budget.used_usd > 0
    ? (budget.avoided_cost / budget.used_usd).toFixed(1)
    : "1.6";

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner onRetry={refetch} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Gasto real" value={`$ ${parseFloat(scaledSpent).toLocaleString("en-US", { minimumFractionDigits: 2 })}`} sub={getTimeRangeLabel(timeRange)} />
        <MetricCard label="Custo evitado" value={`$ ${parseFloat(scaledAvoided).toLocaleString("en-US", { minimumFractionDigits: 2 })}`} sub="via bypass/compressão" accent="text-green-400" />
        <MetricCard label="% do budget" value={`${budget.used_pct.toFixed(1)}%`} sub={`do budget ${getTimeRangeLabel(timeRange)}`} />
        <MetricCard label="ROI AION" value={`${roi}x`} sub="custo evitado / licença" accent="text-[var(--color-primary)]" />
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-5 py-4">
          <h3 className="text-sm font-semibold text-[var(--color-text)]">{t("reports.tabs.opportunity_title")}</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)]">
                {["Intent", "Total", "Taxa bypass", "Confiança"].map((h) => (
                  <th key={h} className="px-5 py-3 text-left text-xs font-medium text-[var(--color-text-muted)]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {mockIntentPerformance
                .filter((i) => (i.bypass_success_rate ?? 0) < 0.85)
                .map((i) => (
                <tr key={i.name} className="border-b border-[var(--color-border)]/50">
                  <td className="px-5 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text)]">{i.name}</td>
                  <td className="px-5 py-3 text-xs text-[var(--color-text-muted)]">{i.requests.toLocaleString("pt-BR")}</td>
                  <td className="px-5 py-3 text-xs font-medium text-amber-400">
                    {((i.bypass_success_rate ?? 0) * 100).toFixed(1)}%
                  </td>
                  <td className="px-5 py-3 text-xs text-[var(--color-text-muted)]">{i.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ShadowTab({ timeRange }: { timeRange: TimeRange }) {
  const t = useT();
  const shadowScalers: Record<TimeRange, number> = {
    live: 0.05,
    "1h": 0.5,
    "4h": 2,
    "24h": 1,
    "2d": 2,
    "7d": 7,
    "14d": 14,
    "30d": 30,
  };
  const scale = shadowScalers[timeRange] || 1;
  const evals = Math.round(14820 * scale);
  const divergences = Math.round(1141 * scale);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Avaliações shadow" value={evals.toLocaleString("pt-BR")} sub={getTimeRangeLabel(timeRange)} />
        <MetricCard label="Concordância" value="92.3%" sub="shadow vs live" accent="text-green-400" />
        <MetricCard label="Divergências" value={divergences.toLocaleString("pt-BR")} sub="entre shadow e live" />
        <MetricCard label="Políticas em teste" value="1" sub="nomos_v2_aggressive" />
      </div>
      <div className="flex items-center gap-3 rounded-xl border border-green-800/40 bg-green-900/10 p-5">
        <CheckCircle2 className="h-5 w-5 shrink-0 text-green-400" />
        <div>
          <p className="text-sm font-semibold text-green-300">nomos_v2_aggressive_bypass</p>
          <p className="text-xs text-green-400/70 mt-0.5">
            92.3% de concordância com a política live. Pronto para promoção após aprovação.
          </p>
        </div>
        <button className="ml-auto rounded-lg bg-green-800/40 px-3 py-1.5 text-xs font-medium text-green-300 hover:bg-green-800/60 transition-colors">
          {t("reports.tabs.promote_live")}
        </button>
      </div>
    </div>
  );
}

function AuditTab({ timeRange }: { timeRange: TimeRange }) {
  const { data: sessionList, isDemo, refetch } = useApiData(getSessions, mockSessions, { intervalMs: 30_000 });
  const recent = sessionList.slice(0, 4);
  const auditScalers: Record<TimeRange, number> = {
    live: 0.05,
    "1h": 0.5,
    "4h": 2,
    "24h": 1,
    "2d": 2,
    "7d": 7,
    "14d": 14,
    "30d": 30,
  };
  const scale = auditScalers[timeRange] || 1;
  const sessionCount = Math.round(12840 * scale);
  const critical = Math.round(14 * scale);

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner onRetry={refetch} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Sessões registradas" value={sessionCount.toLocaleString("pt-BR")} sub={getTimeRangeLabel(timeRange)} />
        <MetricCard label="Com HMAC válido" value="99.97%" sub="integridade garantida" accent="text-green-400" />
        <MetricCard label="Retenção" value="90 dias" sub="conforme política" />
        <MetricCard label="Sessões críticas" value={critical.toString()} sub="risco crítico detectado" accent="text-red-400" />
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-5 py-4">
          <h3 className="text-sm font-semibold text-[var(--color-text)]">Últimas sessões auditadas</h3>
        </div>
        <div className="divide-y divide-[var(--color-border)]/50">
          {recent.map((s) => (
            <div key={s.id} className="flex items-center gap-4 px-5 py-3">
              <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--color-primary)]">{s.id}</span>
              <span className="text-xs text-[var(--color-text-muted)]">{s.turns} turnos</span>
              {s.risk && (
                <Badge variant={s.risk === "critical" || s.risk === "high" ? "error" : s.risk === "medium" ? "warning" : "success"}>
                  {s.risk}
                </Badge>
              )}
              <div className="ml-auto flex items-center gap-1 text-xs">
                {s.hmac_valid === true ? (
                  <><CheckCircle2 className="h-3.5 w-3.5 text-green-400" /><span className="text-green-400">válido</span></>
                ) : s.hmac_valid === false ? (
                  <><AlertTriangle className="h-3.5 w-3.5 text-red-400" /><span className="text-red-400">inválido</span></>
                ) : (
                  <span className="text-[var(--color-text-muted)]">—</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ScheduleTab() {
  const t = useT();
  const mockScheduleFallback: Record<string, unknown> = { schedule: null };
  const { data: scheduleData, isDemo: schedIsDemo, refetch: refetchSched } = useApiData(
    getReportSchedule,
    mockScheduleFallback,
    {},
  );

  const existing = scheduleData.schedule as Record<string, unknown> | null | undefined;

  const [frequency, setFrequency] = useState<"daily" | "weekly" | "monthly">(
    (existing?.frequency as "daily" | "weekly" | "monthly") ?? "monthly",
  );
  const [recipientsRaw, setRecipientsRaw] = useState<string>(
    Array.isArray(existing?.recipients) ? (existing.recipients as string[]).join(", ") : "",
  );
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const recipients = recipientsRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await scheduleReport({ frequency, recipients });
      setSaved(true);
      refetchSched();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : t("reports.tabs.saving"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setSaveError(null);
    try {
      await deleteReportSchedule();
      setRecipientsRaw("");
      setSaved(false);
      refetchSched();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Erro ao remover");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      {schedIsDemo && <DemoBanner onRetry={refetchSched} />}
      {saved && (
        <div className="flex items-center gap-2 rounded-xl border border-green-800/50 bg-green-900/20 px-4 py-3 text-sm text-green-400">
          <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
          {t("reports.tabs.schedule_saved")}
        </div>
      )}

      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 space-y-5">
        <div>
          <h2 className="text-sm font-semibold text-[var(--color-text)]">{t("reports.tabs.schedule_title")}</h2>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            {t("reports.tabs.schedule_subtitle")}
          </p>
        </div>

        {/* Current schedule */}
        {existing && (
          <div className="flex items-start justify-between rounded-lg bg-teal-900/20 border border-teal-800/40 px-4 py-3">
            <div>
              <p className="text-sm font-medium text-teal-400">{t("reports.tabs.active_schedule")}</p>
              <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                Frequência: <strong className="text-teal-300">{existing.frequency as string}</strong>
                {Array.isArray(existing.recipients) && (existing.recipients as string[]).length > 0 && (
                  <> · Destinatários: {(existing.recipients as string[]).join(", ")}</>
                )}
              </p>
            </div>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="ml-3 flex-shrink-0 rounded-lg border border-red-800/40 px-2.5 py-1 text-xs text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-50"
            >
              {deleting ? t("reports.tabs.removing") : t("reports.tabs.remove")}
            </button>
          </div>
        )}

        {/* Frequency selector */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
            Frequência de envio
          </label>
          <div className="flex gap-2">
            {(["daily", "weekly", "monthly"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFrequency(f)}
                className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                  frequency === f
                    ? "border-[var(--color-primary)] bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                    : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                }`}
              >
                {f === "daily" ? "Diário" : f === "weekly" ? "Semanal" : "Mensal"}
              </button>
            ))}
          </div>
        </div>

        {/* Recipients */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
            Destinatários (separados por vírgula)
          </label>
          <input
            type="text"
            value={recipientsRaw}
            onChange={(e) => setRecipientsRaw(e.target.value)}
            placeholder="ciso@empresa.com, cto@empresa.com"
            className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </div>

        {saveError && (
          <div className="rounded-lg bg-red-950/50 px-3 py-2 text-xs text-red-400">
            {saveError}
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={handleSave}
            disabled={saving || !recipientsRaw.trim()}
            className="rounded-lg bg-[var(--color-primary)] px-5 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
          >
            {saving ? "Salvando..." : "Salvar agendamento"}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
        <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
          O que inclui o relatório executivo
        </h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {[
            "Capa com resumo executivo (3 bullet points)",
            "Segurança: bloqueios, PIIs, ameaças, top políticas",
            "Economia: custo vs. baseline, savings, distribuição de modelos",
            "Aprendizado: maturidade dos módulos, recomendações ativas",
          ].map((item, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <span className="mt-1 text-[var(--color-primary)]">→</span>
              <span className="text-[var(--color-text-muted)]">{item}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const TIME_RANGE_DAYS: Record<TimeRange, number> = {
  live: 0, "1h": 0, "4h": 0, "24h": 1, "2d": 2, "7d": 7, "14d": 14, "30d": 30,
};

export function ReportsPage() {
  const t = useT();
  const [activeTab, setActiveTab] = useState<Tab>("exec");
  const [exportOpen, setExportOpen] = useState(false);
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");

  const tabs = TAB_IDS;
  const tabLabels: Record<Tab, string> = {
    exec: t("reports.tabs.exec"),
    security: t("reports.tabs.security"),
    costs: t("reports.tabs.costs"),
    shadow: t("reports.tabs.shadow"),
    audit: t("reports.tabs.audit"),
    schedule: t("reports.tabs.schedule"),
  };
  const tabIcons: Record<Tab, React.ReactNode> = {
    exec: <FileBarChart className="h-4 w-4" />,
    security: <Shield className="h-4 w-4" />,
    costs: <Wallet className="h-4 w-4" />,
    shadow: <FlaskConical className="h-4 w-4" />,
    audit: <ScrollText className="h-4 w-4" />,
    schedule: <Clock className="h-4 w-4" />,
  };

  const handleExport = (fmt: string) => {
    setExportOpen(false);
    const days = TIME_RANGE_DAYS[timeRange] || 30;
    if (fmt === "PDF") {
      const tenant = getActiveTenant();
      window.open(
        `${API_BASE}/v1/reports/${tenant}/executive?format=pdf&days=${days}`,
        "_blank",
      );
      return;
    }
    if (fmt === "JSON") {
      getExecutiveReport("json", days)
        .then((data) => {
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `aion-report-${new Date().toISOString().slice(0, 10)}.json`;
          a.click();
          URL.revokeObjectURL(url);
        })
        .catch(() => {});
      return;
    }
    // PPTX / XLSX — not yet implemented in backend
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            {t("reports.title")}
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Relatório executivo mensal — Abril 2025
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
            <Clock className="h-3.5 w-3.5" />
            Atualizado 5 min atrás
          </div>
          <TimeRangeSelect value={timeRange} onChange={setTimeRange} />
          <div className="relative">
            <button
              onClick={() => setExportOpen((v) => !v)}
              className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2 text-sm font-medium text-[var(--color-text)] hover:bg-white/5 transition-colors"
            >
              <Download className="h-4 w-4" />
              {t("reports.export")}
            </button>
            {exportOpen && (
              <div className="absolute right-0 top-full mt-1 z-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-lg overflow-hidden">
                {exportFormats.map((fmt) => (
                  <button
                    key={fmt}
                    className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)] transition-colors"
                    onClick={() => handleExport(fmt)}
                  >
                    <FileBarChart className="h-3.5 w-3.5" />
                    Exportar como {fmt}
                    {(fmt === "PPTX" || fmt === "XLSX") && (
                      <span className="ml-auto text-[10px] opacity-40">em breve</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--color-border)]">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab
                ? "border-[var(--color-primary)] text-[var(--color-primary)]"
                : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tabIcons[tab]}
            {tabLabels[tab]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "exec" && <ExecTab timeRange={timeRange} />}
      {activeTab === "security" && <SecurityTab timeRange={timeRange} />}
      {activeTab === "costs" && <CostsTab timeRange={timeRange} />}
      {activeTab === "shadow" && <ShadowTab timeRange={timeRange} />}
      {activeTab === "audit" && <AuditTab timeRange={timeRange} />}
      {activeTab === "schedule" && <ScheduleTab />}
    </div>
  );
}
