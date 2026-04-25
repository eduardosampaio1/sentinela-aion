"use client";

import { useState } from "react";
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
import { getStats, getBudgetStatus, getSessions, getExecutiveReport, API_BASE, getActiveTenant } from "@/lib/api";

const tabs = ["Execução", "Segurança", "Custos", "Shadow", "Auditoria"] as const;
type Tab = (typeof tabs)[number];

const tabIcons: Record<Tab, React.ReactNode> = {
  "Execução": <Zap className="h-3.5 w-3.5" />,
  "Segurança": <Shield className="h-3.5 w-3.5" />,
  "Custos": <Wallet className="h-3.5 w-3.5" />,
  "Shadow": <FlaskConical className="h-3.5 w-3.5" />,
  "Auditoria": <ScrollText className="h-3.5 w-3.5" />,
};

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
        <h3 className="mb-4 text-sm font-semibold text-[var(--color-text)]">Performance por módulo</h3>
        <div className="space-y-3">
          {[
            { name: "ESTIXE", requests: 847240, bypassed: 579710, pct: 68.4, color: "bg-teal-500" },
            { name: "NOMOS", requests: 267530, routed: 241600, pct: 90.3, color: "bg-sky-500" },
            { name: "METIS", requests: 241600, compressed: 55568, pct: 23.0, color: "bg-violet-500" },
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

function SecurityTab({ timeRange }: { timeRange: TimeRange }) {
  const totalThreats = mockThreatCategories.reduce((s, t) => s + t.count, 0);
  const threatScalers: Record<TimeRange, number> = {
    live: 0.05,
    "1h": 0.5,
    "4h": 2,
    "24h": 1,
    "2d": 2,
    "7d": 7,
    "14d": 14,
    "30d": 30,
  };
  const scaledThreats = Math.round(totalThreats * (threatScalers[timeRange] || 1));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Ameaças bloqueadas" value={scaledThreats.toLocaleString("pt-BR")} sub={getTimeRangeLabel(timeRange)} accent="text-red-400" />
        <MetricCard label="PIIs interceptadas" value={Math.round(1204 * (threatScalers[timeRange] || 1)).toString()} sub="antes do LLM" accent="text-amber-400" />
        <MetricCard label="Sessões suspeitas" value={Math.round(37 * (threatScalers[timeRange] || 1)).toString()} sub="threat score > 0.8" />
        <MetricCard label="HMAC inválidos" value={Math.max(0, Math.round(3 * (threatScalers[timeRange] || 1))).toString()} sub="possível tampering" accent="text-red-400" />
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-5 py-4">
          <h3 className="text-sm font-semibold text-[var(--color-text)]">Categorias de ameaça</h3>
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
  const { data: budget, isDemo, refetch } = useApiData(getBudgetStatus, mockBudgetSummary, { intervalMs: 60_000 });
  const costScalers: Record<TimeRange, number> = {
    live: 0.05, "1h": 0.5, "4h": 2, "24h": 1, "2d": 2, "7d": 7, "14d": 14, "30d": 30,
  };
  const scale = costScalers[timeRange] || 1;
  const scaledSpent = (budget.used_brl * scale).toFixed(2);
  const scaledAvoided = (budget.avoided_cost * scale).toFixed(2);
  const roi = budget.avoided_cost > 0 && budget.used_brl > 0
    ? (budget.avoided_cost / budget.used_brl).toFixed(1)
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
          <h3 className="text-sm font-semibold text-[var(--color-text)]">Intents com maior oportunidade de economia</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)]">
                {["Intent", "Modelo atual", "Modelo ótimo", "Economia/dia"].map((h) => (
                  <th key={h} className="px-5 py-3 text-left text-xs font-medium text-[var(--color-text-muted)]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {mockIntentPerformance.filter((i) => i.savings_day > 0).map((i) => (
                <tr key={i.name} className="border-b border-[var(--color-border)]/50">
                  <td className="px-5 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text)]">{i.name}</td>
                  <td className="px-5 py-3 text-xs text-[var(--color-text-muted)]">{i.current_model}</td>
                  <td className="px-5 py-3 text-xs text-[var(--color-primary)]">{i.best_model}</td>
                  <td className="px-5 py-3 text-xs font-medium text-green-400">R$ {i.savings_day.toFixed(2)}</td>
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
          Promover para live
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
              <Badge variant={s.risk === "critical" ? "error" : s.risk === "high" ? "error" : s.risk === "medium" ? "warning" : "success"}>
                {s.risk}
              </Badge>
              <div className="ml-auto flex items-center gap-1 text-xs">
                {s.hmac_valid ? (
                  <><CheckCircle2 className="h-3.5 w-3.5 text-green-400" /><span className="text-green-400">válido</span></>
                ) : (
                  <><AlertTriangle className="h-3.5 w-3.5 text-red-400" /><span className="text-red-400">inválido</span></>
                )}
              </div>
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
  const [activeTab, setActiveTab] = useState<Tab>("Execução");
  const [exportOpen, setExportOpen] = useState(false);
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");

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
            Relatórios
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
              Exportar
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
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "Execução" && <ExecTab timeRange={timeRange} />}
      {activeTab === "Segurança" && <SecurityTab timeRange={timeRange} />}
      {activeTab === "Custos" && <CostsTab timeRange={timeRange} />}
      {activeTab === "Shadow" && <ShadowTab timeRange={timeRange} />}
      {activeTab === "Auditoria" && <AuditTab timeRange={timeRange} />}
    </div>
  );
}
