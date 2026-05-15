"use client";

import { Zap, BarChart3, Cpu, ArrowRight, DollarSign, Sparkles } from "lucide-react";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { useApiData } from "@/lib/use-api-data";
import { getBudgetStatus } from "@/lib/api";
import { getGainReport } from "@/lib/api/gains";
import { DemoBanner } from "@/components/ui/demo-banner";
import { mockBudgetSummary, mockIntentPerformance, mockGainReport } from "@/lib/mock-data";
import { useT } from "@/lib/i18n";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtNum(n: number) { return n.toLocaleString("pt-BR"); }
function fmtCost(usd: number) {
  if (usd === 0) return "US$ 0,00";
  if (usd < 0.01) return `US$ ${usd.toFixed(4)}`;
  return `US$ ${usd.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtPct(pct: number) { return `${(pct * 100).toFixed(1)}%`; }

// ─── RankTable ────────────────────────────────────────────────────────────────

function RankTable<T>({
  title,
  rows,
  columns,
  rowKey,
}: {
  title: string;
  rows: T[];
  columns: { label: string; render: (row: T) => React.ReactNode; align?: "left" | "right" }[];
  rowKey: (row: T) => string;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="border-b border-[var(--color-border)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--color-text)]">{title}</h3>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-center text-xs text-[var(--color-text-muted)]">Nenhum dado disponível</p>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              {columns.map((col) => (
                <th key={col.label} className={`px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] ${col.align === "right" ? "text-right" : "text-left"}`}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)} className="border-b border-[var(--color-border)] last:border-0 hover:bg-white/[0.02] transition-colors">
                {columns.map((col) => (
                  <td key={col.label} className={`px-4 py-2.5 text-sm text-[var(--color-text)] ${col.align === "right" ? "text-right font-[family-name:var(--font-mono)]" : ""}`}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const modelBreakdown = [
  { model: "gpt-4o", provider: "OpenAI", requests: 2840, cost_usd: 3680, pct: 58.9, color: "bg-sky-500" },
  { model: "gpt-4o-mini", provider: "OpenAI", requests: 8920, cost_usd: 1640, pct: 26.3, color: "bg-sky-400/60" },
  { model: "claude-3-sonnet", provider: "Anthropic", requests: 1240, cost_usd: 620, pct: 9.9, color: "bg-violet-500" },
  { model: "claude-haiku", provider: "Anthropic", requests: 3120, cost_usd: 308, pct: 4.9, color: "bg-violet-400/60" },
];

const nomosOptimizations = [
  { intent: "limite_cartao_faq", from: "gpt-4o", to: "gpt-4o-mini", count: 2840, saved_day: 2.48 },
  { intent: "taxa_juros_explicacao", from: "gpt-4o", to: "claude-haiku", count: 1540, saved_day: 1.84 },
  { intent: "bloqueio_cartao", from: "gpt-4o-mini", to: "bypass", count: 1210, saved_day: 1.50 },
  { intent: "segunda_via_fatura", from: "gpt-4o", to: "gpt-4o-mini", count: 980, saved_day: 1.16 },
];

const totalNomosRequests = nomosOptimizations.reduce((s, o) => s + o.count, 0);
const totalNomosSavedMonth = nomosOptimizations.reduce((s, o) => s + o.saved_day, 0) * 30;

const bypassCount = 12840;
const daysInPeriod = 24;

export function BudgetPage() {
  const t = useT();
  const { data: budget, isDemo, refetch } = useApiData(getBudgetStatus, mockBudgetSummary, {
    intervalMs: 60_000,
  });
  const { data: gain } = useApiData(getGainReport, mockGainReport);

  const totalWithoutAion = budget.used_usd + budget.avoided_cost;
  const savingsPct = totalWithoutAion > 0
    ? Math.round((budget.avoided_cost / totalWithoutAion) * 100)
    : 0;
  const usedPct = totalWithoutAion > 0
    ? Math.round((budget.used_usd / totalWithoutAion) * 100)
    : 0;
  const projectedMonthly = Math.round((budget.used_usd / daysInPeriod) * 30);

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner onRetry={refetch} />}

      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          {t("budget.title")}
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          {t("budget.subtitle").replace("{n}", String(daysInPeriod))}
        </p>
      </div>

      {/* Hero metrics */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <DollarSign className="h-3.5 w-3.5" />
            {t("budget.metrics.real_cost")}
          </div>
          <p className="mt-2 text-2xl font-bold text-[var(--color-text)]">
            <AnimatedNumber value={budget.used_usd} format={fmtCost} />
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            {t("budget.metrics.without_aion").replace("{value}", fmtCost(totalWithoutAion))}
          </p>
        </div>

        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <Zap className="h-3.5 w-3.5 text-[var(--color-primary)]" />
            {t("budget.metrics.bypass_responses")}
          </div>
          <p className="mt-2 text-2xl font-bold text-[var(--color-text)]">
            <AnimatedNumber value={bypassCount} />
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">{t("budget.metrics.bypass_subtitle")}</p>
        </div>

        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <BarChart3 className="h-3.5 w-3.5" />
            {t("budget.metrics.projection")}
          </div>
          <p className="mt-2 text-2xl font-bold text-[var(--color-text)]">
            <AnimatedNumber value={projectedMonthly} format={fmtCost} />
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            {t("budget.metrics.projection_subtitle").replace("{n}", String(daysInPeriod))}
          </p>
        </div>
      </div>

      {/* Taxa de bypass */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-5 py-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium text-[var(--color-text-muted)]">{t("budget.bypass_rate")}</span>
          <span className="font-[family-name:var(--font-mono)] text-sm font-bold text-[var(--color-primary)]">
            {fmtPct(gain.summary.llm_calls_avoided_pct)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex-1 overflow-hidden rounded-full bg-white/5 h-1.5">
            <div
              className="h-full rounded-full bg-[var(--color-primary)] transition-all duration-500"
              style={{ width: `${Math.min(100, gain.summary.llm_calls_avoided_pct * 100)}%` }}
            />
          </div>
        </div>
      </div>

      {/* 4 tabelas de breakdown */}
      <div className="grid gap-4 lg:grid-cols-2">
        <RankTable
          title={t("budget.tables.top_drivers")}
          rows={gain.breakdowns.top_saving_drivers}
          rowKey={(d) => d.name}
          columns={[
            {
              label: t("budget.tables.driver_col"),
              render: (d) => (
                <span className="flex items-center gap-2">
                  {d.name}
                  {d.is_estimated && (
                    <span className="rounded border border-amber-800/40 px-1 py-0.5 text-[9px] font-semibold uppercase text-amber-400">est.</span>
                  )}
                </span>
              ),
            },
            { label: t("budget.tables.avoided_calls"), render: (d) => fmtNum(d.calls_avoided), align: "right" },
            { label: t("budget.tables.cost_avoided"), render: (d) => fmtCost(d.cost_avoided_usd), align: "right" },
            { label: t("budget.tables.pct"), render: (d) => `${d.pct_of_total_savings.toFixed(1)}%`, align: "right" },
          ]}
        />

        <RankTable
          title={t("budget.tables.top_intents")}
          rows={gain.breakdowns.top_intents}
          rowKey={(i) => i.intent}
          columns={[
            {
              label: t("budget.tables.intent_col"),
              render: (i) => (
                <span className="flex items-center gap-1.5">
                  {i.intent}
                  {i.source === "intent_memory_cumulative" && (
                    <span className="text-[9px] text-[var(--color-text-muted)]">(all-time)</span>
                  )}
                </span>
              ),
            },
            { label: t("budget.tables.avoided_calls"), render: (i) => fmtNum(i.calls_avoided), align: "right" },
            { label: t("budget.tables.cost_avoided"), render: (i) => fmtCost(i.cost_avoided_usd), align: "right" },
            {
              label: t("budget.tables.precision"),
              render: (i) => (
                <span className={i.bypass_accuracy >= 0.9 ? "text-emerald-400" : "text-amber-400"}>
                  {fmtPct(i.bypass_accuracy)}
                </span>
              ),
              align: "right",
            },
          ]}
        />

        <RankTable
          title={t("budget.tables.top_models")}
          rows={gain.breakdowns.top_models}
          rowKey={(m) => m.model_used}
          columns={[
            { label: t("budget.tables.model_col"), render: (m) => m.model_used },
            { label: t("budget.tables.calls_routed"), render: (m) => fmtNum(m.calls_routed), align: "right" },
            { label: t("budget.tables.cost_avoided"), render: (m) => fmtCost(m.cost_avoided_usd), align: "right" },
          ]}
        />

        <RankTable
          title={t("budget.tables.top_strategies")}
          rows={gain.breakdowns.top_strategies}
          rowKey={(s) => s.strategy}
          columns={[
            { label: t("budget.tables.strategy_col"), render: (s) => s.label },
            { label: t("budget.tables.occurrences"), render: (s) => fmtNum(s.count), align: "right" },
            {
              label: "Custo evitado",
              render: (s) => s.cost_avoided_usd > 0 ? fmtCost(s.cost_avoided_usd) : (
                <span className="text-[var(--color-text-muted)]">—</span>
              ),
              align: "right",
            },
          ]}
        />
      </div>

      {/* Custo com AION vs. sem AION */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <h2 className="mb-5 text-sm font-semibold text-[var(--color-text)]">
          {t("budget.comparison.title")}
        </h2>
        <div className="space-y-3">
          {/* Sem AION */}
          <div className="flex items-center gap-4">
            <span className="w-36 shrink-0 text-xs text-[var(--color-text-muted)]">{t("budget.comparison.without_aion")}</span>
            <div className="relative h-8 flex-1 overflow-hidden rounded-lg bg-white/5">
              <div className="h-full w-full rounded-lg bg-red-500/15" />
              <div className="absolute inset-0 flex items-center px-3">
                <span className="text-xs font-semibold text-red-400">
                  {fmtCost(totalWithoutAion)}
                </span>
              </div>
            </div>
          </div>

          {/* Com AION */}
          <div className="flex items-center gap-4">
            <span className="w-36 shrink-0 text-xs text-[var(--color-text-muted)]">{t("budget.comparison.with_aion")}</span>
            <div className="relative h-8 flex-1 overflow-hidden rounded-lg bg-white/5">
              {/* Used portion */}
              <div
                className="h-full rounded-lg bg-green-500/25 border-r-2 border-green-400/60 transition-all duration-700"
                style={{ width: `${usedPct}%` }}
              />
              {/* Saved label inside the remaining space */}
              <div className="absolute inset-0 flex items-center">
                <div className="px-3" style={{ width: `${usedPct}%` }}>
                  <span className="text-xs font-semibold text-green-400">
                    {fmtCost(budget.used_usd)}
                  </span>
                </div>
                <div className="flex-1 px-3">
                  <span className="text-xs text-green-400/50">
                    ← {fmtCost(budget.avoided_cost)} {t("budget.comparison.saved")}
                  </span>
                </div>
              </div>
            </div>
            <span className="shrink-0 rounded-full bg-green-500/10 px-2.5 py-1 text-xs font-bold text-green-400 ring-1 ring-green-500/30">
              -{savingsPct}%
            </span>
          </div>
        </div>
        <p className="mt-4 text-xs text-[var(--color-text-muted)]">
          Estimativa "sem AION" considera 100% das conversas roteadas para gpt-4o sem bypass nem compressão de contexto.
        </p>
      </div>

      {/* 2-col: Custo por modelo + Otimizações de roteamento */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Custo por modelo */}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <h2 className="mb-5 flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <Cpu className="h-4 w-4 text-[var(--color-primary)]" />
            {t("budget.model_cost.title")}
          </h2>
          <div className="space-y-4">
            {modelBreakdown.map((m) => (
              <div key={m.model}>
                <div className="mb-1.5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${m.color}`} />
                    <span className="text-sm font-medium text-[var(--color-text)]">{m.model}</span>
                    <span className="text-xs text-[var(--color-text-muted)]">{m.provider}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-[var(--color-text-muted)]">
                      {m.requests.toLocaleString("pt-BR")} req
                    </span>
                    <span className="w-24 text-right font-mono text-sm font-semibold text-[var(--color-text)]">
                      {fmtCost(m.cost_usd)}
                    </span>
                  </div>
                </div>
                <div className="h-1.5 w-full rounded-full bg-white/10">
                  <div
                    className={`h-1.5 rounded-full transition-all duration-700 ${m.color}`}
                    style={{ width: `${m.pct}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs text-[var(--color-text-muted)]">
            gpt-4o responde por {modelBreakdown[0].pct}% do custo com apenas {modelBreakdown[0].requests.toLocaleString("pt-BR")} requests.
          </p>
        </div>

        {/* Otimizações automáticas de roteamento */}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <Sparkles className="h-4 w-4 text-[var(--color-primary)]" />
            {t("budget.nomos.title")}
          </h2>
          <p className="mb-4 text-xs text-[var(--color-text-muted)]">
            {t("budget.nomos.subtitle")
              .replace("{requests}", totalNomosRequests.toLocaleString("pt-BR"))
              .replace("{saved}", fmtCost(totalNomosSavedMonth))}
          </p>
          <div className="space-y-2.5">
            {nomosOptimizations.map((o) => (
              <div
                key={o.intent}
                className="flex items-center justify-between rounded-lg bg-white/5 px-3 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-xs font-medium text-[var(--color-text)]">
                    {o.intent}
                  </p>
                  <div className="mt-1 flex items-center gap-1.5">
                    <span className="rounded bg-white/5 px-1.5 py-0.5 text-xs text-[var(--color-text-muted)]">
                      {o.from}
                    </span>
                    <ArrowRight className="h-3 w-3 shrink-0 text-green-400" />
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                        o.to === "bypass"
                          ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                          : "bg-green-500/10 text-green-400"
                      }`}
                    >
                      {o.to === "bypass" ? "⚡ bypass" : o.to}
                    </span>
                  </div>
                </div>
                <div className="ml-4 shrink-0 text-right">
                  <p className="font-mono text-xs font-bold text-green-400">
                    +{fmtCost(o.saved_day * 30)}/mês
                  </p>
                  <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                    {o.count.toLocaleString("pt-BR")} req
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Intents que mais consomem tokens */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-6 py-4">
          <h2 className="text-sm font-semibold text-[var(--color-text)]">
            Intents que mais consomem tokens
          </h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
            Categorias com oportunidade de troca de modelo destacadas — aplique em{" "}
            <a href="/routing" className="text-[var(--color-primary)] hover:underline underline-offset-2">
              Roteamento
            </a>
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                <th className="px-6 py-3 font-medium">Intent</th>
                <th className="px-4 py-3 text-right font-medium">Req / dia</th>
                <th className="px-4 py-3 font-medium">Taxa bypass</th>
                <th className="px-4 py-3 text-right font-medium">Custo médio</th>
                <th className="px-4 py-3 text-right font-medium">Confiança</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {mockIntentPerformance.map((intent) => {
                // Intents with low bypass rate are "optimization opportunities"
                const bypassRate = intent.bypass_success_rate ?? 1;
                const hasOpportunity = bypassRate < 0.85;
                const confStr = intent.confidence;
                const confColor =
                  confStr === "high" ? "text-green-400"
                  : confStr === "medium" ? "text-amber-400"
                  : "text-[var(--color-text-muted)]";
                return (
                  <tr
                    key={intent.name}
                    className={`transition-colors hover:bg-white/5 ${
                      hasOpportunity ? "bg-amber-500/[0.04]" : ""
                    }`}
                  >
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2">
                        {hasOpportunity ? (
                          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                        ) : (
                          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-green-500/40" />
                        )}
                        <span className="font-mono text-xs font-medium text-[var(--color-text)]">
                          {intent.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-[var(--color-text-muted)]">
                      {intent.requests.toLocaleString("pt-BR")}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`text-xs font-semibold ${hasOpportunity ? "text-amber-400" : "text-green-400"}`}>
                        {(bypassRate * 100).toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-[var(--color-text-muted)]">
                      {intent.avg_cost_when_forwarded !== undefined && intent.avg_cost_when_forwarded > 0
                        ? `$${intent.avg_cost_when_forwarded.toFixed(5)}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`text-xs font-semibold ${confColor}`}>{confStr}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="border-t border-[var(--color-border)] px-6 py-3 flex items-center justify-between">
          <p className="text-xs text-[var(--color-text-muted)]">
            <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-400 align-middle" />
            Taxa de bypass abaixo de 85% — oportunidade de otimização
            <span className="mx-3 text-[var(--color-border)]">·</span>
            <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-green-500/40 align-middle" />
            Intent bem calibrado
          </p>
          <p className="text-xs text-[var(--color-text-muted)]">
            {mockIntentPerformance.filter((i) => (i.bypass_success_rate ?? 1) >= 0.85).length} intents otimizados
          </p>
        </div>
      </div>
    </div>
  );
}
