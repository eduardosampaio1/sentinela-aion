"use client";

import { TrendingDown, Zap, BarChart3, Cpu, ArrowRight, Sparkles, DollarSign } from "lucide-react";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { useApiData } from "@/lib/use-api-data";
import { getBudgetStatus } from "@/lib/api";
import { DemoBanner } from "@/components/ui/demo-banner";
import { mockBudgetSummary, mockIntentPerformance } from "@/lib/mock-data";

const modelBreakdown = [
  { model: "gpt-4o", provider: "OpenAI", requests: 2840, cost_brl: 18400, pct: 58.9, color: "bg-sky-500" },
  { model: "gpt-4o-mini", provider: "OpenAI", requests: 8920, cost_brl: 8200, pct: 26.3, color: "bg-sky-400/60" },
  { model: "claude-3-sonnet", provider: "Anthropic", requests: 1240, cost_brl: 3100, pct: 9.9, color: "bg-violet-500" },
  { model: "claude-haiku", provider: "Anthropic", requests: 3120, cost_brl: 1540, pct: 4.9, color: "bg-violet-400/60" },
];

const nomosOptimizations = [
  { intent: "limite_cartao_faq", from: "gpt-4o", to: "gpt-4o-mini", count: 2840, saved_day: 12.40 },
  { intent: "taxa_juros_explicacao", from: "gpt-4o", to: "claude-haiku", count: 1540, saved_day: 9.20 },
  { intent: "bloqueio_cartao", from: "gpt-4o-mini", to: "bypass", count: 1210, saved_day: 7.50 },
  { intent: "segunda_via_fatura", from: "gpt-4o", to: "gpt-4o-mini", count: 980, saved_day: 5.80 },
];

const totalNomosRequests = nomosOptimizations.reduce((s, o) => s + o.count, 0);
const totalNomosSavedMonth = nomosOptimizations.reduce((s, o) => s + o.saved_day, 0) * 30;

const bypassCount = 12840;
const daysInPeriod = 24;

export function BudgetPage() {
  const { data: budget, isDemo, refetch } = useApiData(getBudgetStatus, mockBudgetSummary, {
    intervalMs: 60_000,
  });

  const totalWithoutAion = budget.used_brl + budget.avoided_cost;
  const savingsPct = totalWithoutAion > 0
    ? Math.round((budget.avoided_cost / totalWithoutAion) * 100)
    : 0;
  const usedPct = totalWithoutAion > 0
    ? Math.round((budget.used_brl / totalWithoutAion) * 100)
    : 0;
  const projectedMonthly = Math.round((budget.used_brl / daysInPeriod) * 30);

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner onRetry={refetch} />}

      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          Economia
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          O que o AION economizou e onde o dinheiro está indo — últimos {daysInPeriod} dias
        </p>
      </div>

      {/* Hero metrics */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {/* Economia gerada — hero metric */}
        <div className="col-span-2 rounded-xl border border-green-500/30 bg-green-950/30 p-5 lg:col-span-1">
          <div className="flex items-center gap-2 text-xs text-green-400">
            <TrendingDown className="h-3.5 w-3.5" />
            Economia gerada
          </div>
          <p className="mt-2 font-[family-name:var(--font-heading)] text-3xl font-bold text-green-400">
            R$ <AnimatedNumber value={budget.avoided_cost} />
          </p>
          <p className="mt-1 text-xs text-green-400/70">
            {savingsPct}% do custo evitado — via bypass e compressão
          </p>
        </div>

        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <DollarSign className="h-3.5 w-3.5" />
            Custo real do mês
          </div>
          <p className="mt-2 text-2xl font-bold text-[var(--color-text)]">
            R$ <AnimatedNumber value={budget.used_brl} />
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            vs R$ {totalWithoutAion.toLocaleString("pt-BR")} sem AION
          </p>
        </div>

        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <Zap className="h-3.5 w-3.5 text-[var(--color-primary)]" />
            Respostas sem LLM
          </div>
          <p className="mt-2 text-2xl font-bold text-[var(--color-text)]">
            <AnimatedNumber value={bypassCount} />
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">bypass e cache — custo zero</p>
        </div>

        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <BarChart3 className="h-3.5 w-3.5" />
            Projeção 30 dias
          </div>
          <p className="mt-2 text-2xl font-bold text-[var(--color-text)]">
            R$ <AnimatedNumber value={projectedMonthly} />
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            baseado nos últimos {daysInPeriod} dias
          </p>
        </div>
      </div>

      {/* Custo com AION vs. sem AION */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <h2 className="mb-5 text-sm font-semibold text-[var(--color-text)]">
          Custo com AION vs. sem AION este mês
        </h2>
        <div className="space-y-3">
          {/* Sem AION */}
          <div className="flex items-center gap-4">
            <span className="w-36 shrink-0 text-xs text-[var(--color-text-muted)]">Sem AION (estimado)</span>
            <div className="relative h-8 flex-1 overflow-hidden rounded-lg bg-white/5">
              <div className="h-full w-full rounded-lg bg-red-500/15" />
              <div className="absolute inset-0 flex items-center px-3">
                <span className="text-xs font-semibold text-red-400">
                  R$ {totalWithoutAion.toLocaleString("pt-BR")}
                </span>
              </div>
            </div>
          </div>

          {/* Com AION */}
          <div className="flex items-center gap-4">
            <span className="w-36 shrink-0 text-xs text-[var(--color-text-muted)]">Com AION (real)</span>
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
                    R$ {budget.used_brl.toLocaleString("pt-BR")}
                  </span>
                </div>
                <div className="flex-1 px-3">
                  <span className="text-xs text-green-400/50">
                    ← R$ {budget.avoided_cost.toLocaleString("pt-BR")} economizados
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

      {/* 2-col: Custo por modelo + Otimizações NOMOS */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Custo por modelo */}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <h2 className="mb-5 flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <Cpu className="h-4 w-4 text-[var(--color-primary)]" />
            Custo por modelo
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
                      R$ {m.cost_brl.toLocaleString("pt-BR")}
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

        {/* Otimizações automáticas NOMOS */}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <Sparkles className="h-4 w-4 text-[var(--color-primary)]" />
            Otimizações automáticas do NOMOS
          </h2>
          <p className="mb-4 text-xs text-[var(--color-text-muted)]">
            {totalNomosRequests.toLocaleString("pt-BR")} requests direcionados para o modelo mais eficiente —{" "}
            <span className="font-semibold text-green-400">
              R$ {Math.round(totalNomosSavedMonth).toLocaleString("pt-BR")} economizados no mês
            </span>
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
                    +R$ {(o.saved_day * 30).toFixed(0)}/mês
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
                <th className="px-4 py-3 font-medium">Modelo atual</th>
                <th className="px-4 py-3 font-medium">Melhor modelo</th>
                <th className="px-4 py-3 text-right font-medium">Economia / dia</th>
                <th className="px-4 py-3 text-right font-medium">Confiança</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {mockIntentPerformance.map((intent) => {
                const hasOpportunity = intent.savings_day > 0;
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
                    <td className="px-4 py-3">
                      <span className="rounded bg-white/5 px-2 py-0.5 text-xs text-[var(--color-text-muted)]">
                        {intent.current_model}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${
                          intent.best_model === intent.current_model
                            ? "bg-white/5 text-[var(--color-text-muted)]"
                            : intent.best_model === "bypass"
                            ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                            : "bg-amber-500/10 text-amber-400"
                        }`}
                      >
                        {intent.best_model === intent.current_model
                          ? "otimizado ✓"
                          : intent.best_model === "bypass"
                          ? "⚡ bypass"
                          : intent.best_model}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {intent.savings_day > 0 ? (
                        <span className="font-mono text-xs font-bold text-green-400">
                          +R$ {intent.savings_day.toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-xs text-[var(--color-text-muted)]">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span
                        className={`text-xs font-semibold ${
                          intent.confidence >= 0.9
                            ? "text-green-400"
                            : intent.confidence >= 0.8
                            ? "text-amber-400"
                            : "text-[var(--color-text-muted)]"
                        }`}
                      >
                        {(intent.confidence * 100).toFixed(0)}%
                      </span>
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
            Oportunidade de otimização detectada pelo NOMOS
            <span className="mx-3 text-[var(--color-border)]">·</span>
            <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-green-500/40 align-middle" />
            Modelo já otimizado
          </p>
          <p className="text-xs text-green-400 font-medium">
            Potencial: +R$ {mockIntentPerformance.reduce((s, i) => s + i.savings_day, 0).toFixed(2)}/dia
          </p>
        </div>
      </div>
    </div>
  );
}
