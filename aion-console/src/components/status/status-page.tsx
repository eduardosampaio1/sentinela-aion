"use client";

import { useState } from "react";
import {
  Zap,
  DollarSign,
  Shield,
  GitBranch,
  Gauge,
  Clock,
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
  TrendingDown,
  Brain,
  Activity,
  Database,
  Wand2,
  ScanEye,
  Check,
  X,
  ChevronRight,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { useAionData } from "@/lib/use-aion-data";
import { mockSpendTrend, mockModelCostDistribution } from "@/lib/mock-data";
import type { ServiceStatus } from "@/lib/types";

const fmtBRL = (n: number) => `R$ ${n.toFixed(2)}`;
const fmtPct = (n: number) => `${Math.round(n)}%`;
const fmtInt = (n: number) => Math.round(n).toLocaleString("pt-BR");

export function StatusPage() {
  const [autoRefresh, setAutoRefresh] = useState(true);

  // Single data source: fetches real API, falls back to mocks when offline.
  const liveData = useAionData(3000, autoRefresh);

  const stats = liveData.stats;
  const modules = liveData.modules;
  const dist = liveData.distribution;
  const opState = liveData.operational;
  const status: ServiceStatus = liveData.connected ? "online" : "offline";

  const recentEvents = liveData.events.slice(0, 5);

  const totalEconomy = modules.nomos.cost_optimized + modules.estixe.cost_avoided + modules.metis.cost_saved;

  return (
    <div className="space-y-6">
      {/* ═══ HERO OPERACIONAL ═══ */}
      <div className="rounded-2xl border border-[var(--color-primary)]/20 bg-gradient-to-br from-[var(--color-primary)]/5 to-[var(--color-bg)] p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--color-primary)]/10">
              <Activity className={`h-7 w-7 ${status === "online" ? "text-[var(--color-primary)]" : "text-red-500"}`} />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="font-[family-name:var(--font-heading)] text-xl font-bold text-[var(--color-text)]">
                  AION
                </h1>
                <Badge variant={status === "online" ? "success" : "error"} dot pulse={status === "online"}>
                  {status === "online" ? "Online" : "Offline"}
                </Badge>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <span className="text-sm font-semibold text-[var(--color-primary)]">
                  {opState.mode_label}
                </span>
                <span className="text-xs text-[var(--color-text-muted)]">
                  — {opState.mode_description}
                </span>
              </div>
            </div>
          </div>

          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              autoRefresh
                ? "border-[var(--color-primary)] bg-[var(--color-primary)]/5 text-[var(--color-primary)]"
                : "border-[var(--color-border)] text-[var(--color-text-muted)]"
            }`}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${autoRefresh ? "animate-spin" : ""}`} style={autoRefresh ? { animationDuration: "3s" } : undefined} />
            {autoRefresh ? "Ao vivo" : "Pausado"}
          </button>
        </div>

        {/* Impact Numbers */}
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-xl bg-[var(--color-surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
              <Zap className="h-3.5 w-3.5 text-[var(--color-secondary)]" />
              Chamadas evitadas
            </div>
            <AnimatedNumber
              value={stats.bypasses}
              className="mt-2 block font-[family-name:var(--font-mono)] text-2xl font-bold text-[var(--color-text)]"
            />
            <div className="mt-0.5 text-xs text-[var(--color-success)]">
              <AnimatedNumber value={(stats.bypasses / stats.total_requests) * 100} format={fmtPct} />
              {" "}do total
            </div>
          </div>

          <div className="rounded-xl bg-[var(--color-surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
              <DollarSign className="h-3.5 w-3.5 text-green-600" />
              Economizado hoje
            </div>
            <AnimatedNumber
              value={stats.cost_saved}
              format={fmtBRL}
              className="mt-2 block font-[family-name:var(--font-mono)] text-2xl font-bold text-green-400"
            />
            <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
              <AnimatedNumber value={stats.tokens_saved} /> tokens poupados
            </div>
          </div>

          <div className="rounded-xl bg-[var(--color-surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
              <Shield className="h-3.5 w-3.5 text-red-500" />
              Ameaças bloqueadas
            </div>
            <AnimatedNumber
              value={modules.estixe.threats_detected}
              className="mt-2 block font-[family-name:var(--font-mono)] text-2xl font-bold text-[var(--color-text)]"
            />
            <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
              <AnimatedNumber value={stats.blocks} /> bloqueios totais
            </div>
          </div>

          <div className="rounded-xl bg-[var(--color-surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
              <Gauge className="h-3.5 w-3.5 text-[var(--color-primary)]" />
              Latência média
            </div>
            <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-[var(--color-text)]">
              <AnimatedNumber value={stats.avg_latency_ms} /><span className="text-sm font-medium text-[var(--color-text-muted)]">ms</span>
            </div>
            <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
              <AnimatedNumber value={(1 - stats.errors / stats.total_requests) * 100} format={(n) => `${n.toFixed(1)}%`} /> sem fallback
            </div>
          </div>
        </div>

        {/* Guardrails status */}
        <div className="mt-4 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
          <ShieldCheck className="h-3.5 w-3.5 text-[var(--color-primary)]" />
          <span>
            <strong className="text-[var(--color-text)]">{opState.active_guardrails}/{opState.total_guardrails}</strong> guardrails ativos
          </span>
          <span className="mx-1">·</span>
          <span>
            Modelo principal: <strong className="font-[family-name:var(--font-mono)] text-[var(--color-text)]">{stats.top_model}</strong>
          </span>
          <span className="mx-1">·</span>
          <span>
            Uptime: <strong className="text-[var(--color-text)] font-[family-name:var(--font-mono)]">
              <AnimatedNumber value={opState.uptime_hours} format={(n) => `${n.toFixed(1)}h`} />
            </strong>
          </span>
        </div>
      </div>

      {/* ═══ RECOMENDAÇÃO NEMOS ═══ */}
      <NemosRecommendationCard />

      {/* ═══ GRÁFICOS ═══ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Spend trend — 2/3 width */}
        <div className="lg:col-span-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <TrendingDown className="h-4 w-4 text-green-400" />
            Gasto vs. Custo evitado (abril)
          </h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">R$ por dia</p>
          <div className="mt-4 h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={mockSpendTrend} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="gradSpend" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gradAvoided" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  tick={{ fill: "var(--color-text-muted)", fontSize: 10 }}
                  tickFormatter={(v: string) => v.slice(8)}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  tick={{ fill: "var(--color-text-muted)", fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => `${v}`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--color-surface)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "8px",
                    fontSize: 12,
                  }}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  labelFormatter={(v: any) => `Dia ${String(v).slice(8)}/04`}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  formatter={(v: any, name: any) => [
                    `R$ ${Number(v).toLocaleString("pt-BR")}`,
                    name === "spend" ? "Gasto" : "Evitado",
                  ]}
                />
                <Area type="monotone" dataKey="spend" stroke="#0ea5e9" strokeWidth={2} fill="url(#gradSpend)" />
                <Area type="monotone" dataKey="avoided" stroke="#22c55e" strokeWidth={2} fill="url(#gradAvoided)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Model cost distribution — 1/3 width */}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <h2 className="text-sm font-semibold text-[var(--color-text)]">Distribuição de custo</h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">Por modelo (% do total)</p>
          <div className="mt-4 h-48">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={mockModelCostDistribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={48}
                  outerRadius={72}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {mockModelCostDistribution.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Pie>
                <Legend
                  iconSize={8}
                  formatter={(value: string) => (
                    <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{value}</span>
                  )}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--color-surface)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "8px",
                    fontSize: 12,
                  }}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  formatter={(v: any) => [`${v}%`, "Custo"]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ═══ DECISÕES VIVAS ═══ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Decision Distribution */}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <Brain className="h-4 w-4 text-[var(--color-primary)]" />
            Inteligência em ação
          </h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">Como o AION está decidindo agora</p>

          <div className="mt-5 space-y-3">
            <DistributionBar label="Bypass (ESTIXE)" pct={dist.bypass_pct} color="bg-teal-500" />
            <DistributionBar label="Modelo leve" pct={dist.light_model_pct} color="bg-sky-400" />
            <DistributionBar label="Modelo padrão" pct={dist.standard_model_pct} color="bg-blue-500" />
            <DistributionBar label="Modelo premium" pct={dist.premium_model_pct} color="bg-violet-500" />
            <DistributionBar label="Fallback" pct={dist.fallback_pct} color="bg-amber-400" />
            <DistributionBar label="Bloqueado" pct={dist.blocked_pct} color="bg-red-400" />
          </div>

          <div className="mt-4 rounded-lg bg-white/5 px-3 py-2 text-xs text-[var(--color-text-muted)]">
            <strong className="text-[var(--color-text)]">
              <AnimatedNumber value={dist.bypass_pct + dist.light_model_pct} />%
            </strong> das requisições resolvidas com custo mínimo
          </div>
        </div>

        {/* Live Feed */}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <Activity className="h-4 w-4 text-[var(--color-primary)]" />
            Últimas decisões
          </h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">Fluxo em tempo real</p>

          <div className="mt-4 space-y-2">
            {recentEvents.map((evt) => (
              <div
                key={evt.id}
                className="flex items-center gap-3 rounded-lg border border-[var(--color-border)] px-3 py-2.5 transition-colors hover:bg-white/5"
              >
                <ModuleBadge module={evt.module} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-[var(--color-text)]">{evt.input}</div>
                </div>
                <DecisionBadge decision={evt.decision} />
                <span className="shrink-0 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                  {evt.response_time_ms}ms
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ═══ MÓDULOS PROTAGONISTAS ═══ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* NOMOS */}
        <div className="rounded-xl border border-sky-800/50 bg-gradient-to-br from-sky-950/50 to-transparent p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-900/30">
              <GitBranch className="h-4 w-4 text-sky-400" />
            </div>
            <div>
              <h3 className="font-[family-name:var(--font-heading)] text-sm font-bold text-sky-200">NOMOS</h3>
              <span className="text-xs text-sky-600">Roteamento inteligente</span>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-sky-600">Decisões hoje</div>
              <AnimatedNumber value={modules.nomos.decisions_today} className="font-[family-name:var(--font-mono)] text-lg font-bold text-sky-200" />
            </div>
            <div>
              <div className="text-xs text-sky-600">Custo otimizado</div>
              <AnimatedNumber value={modules.nomos.cost_optimized} format={fmtBRL} className="font-[family-name:var(--font-mono)] text-lg font-bold text-green-400" />
            </div>
            <div>
              <div className="text-xs text-sky-600">→ Modelo leve</div>
              <AnimatedNumber value={modules.nomos.routes_to_light} className="font-[family-name:var(--font-mono)] text-sm font-semibold text-sky-200" />
            </div>
            <div>
              <div className="text-xs text-sky-600">→ Premium</div>
              <AnimatedNumber value={modules.nomos.routes_to_premium} className="font-[family-name:var(--font-mono)] text-sm font-semibold text-sky-200" />
            </div>
          </div>

          <div className="mt-3 flex items-center gap-1.5 text-xs text-sky-400">
            <Clock className="h-3 w-3" />
            Tempo médio de decisão: <strong><AnimatedNumber value={modules.nomos.avg_decision_ms} />ms</strong>
          </div>
        </div>

        {/* ESTIXE */}
        <div className="rounded-xl border border-teal-800/50 bg-gradient-to-br from-teal-950/50 to-transparent p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-900/30">
              <Shield className="h-4 w-4 text-teal-400" />
            </div>
            <div>
              <h3 className="font-[family-name:var(--font-heading)] text-sm font-bold text-teal-200">ESTIXE</h3>
              <span className="text-xs text-teal-600">Controle e proteção</span>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-teal-600">Desvios hoje</div>
              <AnimatedNumber value={modules.estixe.bypasses_today} className="font-[family-name:var(--font-mono)] text-lg font-bold text-teal-200" />
            </div>
            <div>
              <div className="text-xs text-teal-600">Custo evitado</div>
              <AnimatedNumber value={modules.estixe.cost_avoided} format={fmtBRL} className="font-[family-name:var(--font-mono)] text-lg font-bold text-green-400" />
            </div>
            <div>
              <div className="text-xs text-teal-600">Bloqueios</div>
              <AnimatedNumber value={modules.estixe.blocks_today} className="font-[family-name:var(--font-mono)] text-sm font-semibold text-teal-200" />
            </div>
            <div>
              <div className="text-xs text-red-600">Ameaças</div>
              <AnimatedNumber value={modules.estixe.threats_detected} className="font-[family-name:var(--font-mono)] text-sm font-semibold text-red-400" />
            </div>
          </div>

          <div className="mt-3 flex items-center gap-1.5 text-xs text-teal-400">
            <TrendingDown className="h-3 w-3" />
            <AnimatedNumber value={modules.estixe.tokens_saved} /> tokens poupados
          </div>
        </div>

        {/* METIS */}
        <div className="rounded-xl border border-violet-800/50 bg-gradient-to-br from-violet-950/50 to-transparent p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-900/30">
              <Gauge className="h-4 w-4 text-violet-400" />
            </div>
            <div>
              <h3 className="font-[family-name:var(--font-heading)] text-sm font-bold text-violet-200">METIS</h3>
              <span className="text-xs text-violet-600">Otimização</span>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-violet-600">Otimizações</div>
              <AnimatedNumber value={modules.metis.optimizations_today} className="font-[family-name:var(--font-mono)] text-lg font-bold text-violet-200" />
            </div>
            <div>
              <div className="text-xs text-violet-600">Custo reduzido</div>
              <AnimatedNumber value={modules.metis.cost_saved} format={fmtBRL} className="font-[family-name:var(--font-mono)] text-lg font-bold text-green-400" />
            </div>
            <div>
              <div className="text-xs text-violet-600">Tokens comprimidos</div>
              <AnimatedNumber value={modules.metis.tokens_compressed} className="font-[family-name:var(--font-mono)] text-sm font-semibold text-violet-200" />
            </div>
            <div>
              <div className="text-xs text-violet-600">Redução média</div>
              <div className="font-[family-name:var(--font-mono)] text-sm font-semibold text-violet-200">
                -<AnimatedNumber value={modules.metis.avg_reduction_pct} />%
              </div>
            </div>
          </div>

          <div className="mt-3 flex items-center gap-1.5 text-xs text-violet-400">
            <TrendingDown className="h-3 w-3" />
            Economia acumulada: <strong><AnimatedNumber value={totalEconomy} format={fmtBRL} /></strong>
          </div>
        </div>
      </div>

      {/* ═══ v1.5 INTELLIGENCE ═══ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* SEMANTIC CACHE */}
        <div className="rounded-xl border border-amber-800/50 bg-gradient-to-br from-amber-950/50 to-transparent p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-900/30">
              <Database className="h-4 w-4 text-amber-400" />
            </div>
            <div>
              <h3 className="font-[family-name:var(--font-heading)] text-sm font-bold text-amber-200">CACHE</h3>
              <span className="text-xs text-amber-600">Cache semântico</span>
            </div>
            <span className="ml-auto">
              <Badge variant={modules.cache.enabled ? "success" : "warning"}>
                {modules.cache.enabled ? "Ativo" : "Desligado"}
              </Badge>
            </span>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-amber-600">Hit rate</div>
              <div className="font-[family-name:var(--font-mono)] text-lg font-bold text-amber-200">
                <AnimatedNumber value={modules.cache.hit_rate * 100} format={fmtPct} />
              </div>
            </div>
            <div>
              <div className="text-xs text-amber-600">Entradas</div>
              <AnimatedNumber value={modules.cache.total_entries} className="font-[family-name:var(--font-mono)] text-lg font-bold text-amber-200" />
            </div>
            <div>
              <div className="text-xs text-green-600">Hits</div>
              <AnimatedNumber value={modules.cache.hits} className="font-[family-name:var(--font-mono)] text-sm font-semibold text-green-400" />
            </div>
            <div>
              <div className="text-xs text-amber-600">Misses</div>
              <AnimatedNumber value={modules.cache.misses} className="font-[family-name:var(--font-mono)] text-sm font-semibold text-amber-200" />
            </div>
          </div>

          <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-400">
            <TrendingDown className="h-3 w-3" />
            <AnimatedNumber value={modules.cache.invalidations} /> invalidações · <AnimatedNumber value={modules.cache.evictions} /> evições
          </div>
        </div>

        {/* PROMPT REWRITER */}
        <div className="rounded-xl border border-rose-800/50 bg-gradient-to-br from-rose-950/50 to-transparent p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-900/30">
              <Wand2 className="h-4 w-4 text-rose-400" />
            </div>
            <div>
              <h3 className="font-[family-name:var(--font-heading)] text-sm font-bold text-rose-200">REWRITER</h3>
              <span className="text-xs text-rose-600">Prompt enhancement</span>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-rose-600">Rewrites hoje</div>
              <AnimatedNumber value={modules.metis.rewrites_applied} className="font-[family-name:var(--font-mono)] text-lg font-bold text-rose-200" />
            </div>
            <div>
              <div className="text-xs text-rose-600">Taxa de rewrite</div>
              <div className="font-[family-name:var(--font-mono)] text-lg font-bold text-rose-200">
                <AnimatedNumber value={modules.metis.optimizations_today > 0 ? (modules.metis.rewrites_applied / modules.metis.optimizations_today) * 100 : 0} format={fmtPct} />
              </div>
            </div>
          </div>

          <div className="mt-3 text-xs text-rose-400">
            Apenas adiciona especificidade — nunca muda intenção
          </div>
        </div>

        {/* NER + CLASSIFIER */}
        <div className="rounded-xl border border-cyan-800/50 bg-gradient-to-br from-cyan-950/50 to-transparent p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-900/30">
              <ScanEye className="h-4 w-4 text-cyan-400" />
            </div>
            <div>
              <h3 className="font-[family-name:var(--font-heading)] text-sm font-bold text-cyan-200">NER + CLASSIFIER</h3>
              <span className="text-xs text-cyan-600">Inteligência híbrida</span>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-cyan-600">Falsos positivos evitados</div>
              <AnimatedNumber value={modules.estixe.false_positives_avoided} className="font-[family-name:var(--font-mono)] text-lg font-bold text-cyan-200" />
            </div>
            <div>
              <div className="text-xs text-cyan-600">Classificador</div>
              <div className="font-[family-name:var(--font-mono)] text-lg font-bold text-cyan-200">
                {modules.nomos.classifier_method === "hybrid" ? "Híbrido" : "Heurístico"}
              </div>
            </div>
          </div>

          <div className="mt-3 text-xs text-cyan-400">
            {modules.nomos.classifier_method === "hybrid"
              ? "70% semântico + 30% heurístico"
              : "Fallback: apenas heurístico"}
          </div>
        </div>
      </div>

      {/* ═══ FOOTER ═══ */}
      <div className="flex items-center justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-4">
        <div className="flex items-center gap-6 text-sm">
          <div>
            <span className="text-[var(--color-text-muted)]">Total processado: </span>
            <AnimatedNumber value={stats.total_requests} className="font-[family-name:var(--font-mono)] font-bold text-[var(--color-text)]" />
          </div>
          <div>
            <span className="text-[var(--color-text-muted)]">Economia total: </span>
            <AnimatedNumber value={stats.cost_saved} format={fmtBRL} className="font-[family-name:var(--font-mono)] font-bold text-green-400" />
          </div>
          <div>
            <span className="text-[var(--color-text-muted)]">Erros: </span>
            <AnimatedNumber value={stats.errors} className="font-[family-name:var(--font-mono)] font-bold text-[var(--color-text)]" />
            <span className="text-xs text-[var(--color-text-muted)]"> (</span>
            <AnimatedNumber value={(stats.errors / stats.total_requests) * 100} format={(n) => `${n.toFixed(1)}%`} className="text-xs text-[var(--color-text-muted)]" />
            <span className="text-xs text-[var(--color-text-muted)]">)</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {liveData.connected ? (
            <div className="flex items-center gap-1.5 text-xs text-[var(--color-success)]">
              <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
              API conectada
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-amber-500">
              <AlertTriangle className="h-3.5 w-3.5" />
              Dados simulados
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ═══ Sub-components ═══

function DistributionBar({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-32 text-right text-xs text-[var(--color-text-muted)]">{label}</span>
      <div className="flex-1">
        <div className="h-4 w-full overflow-hidden rounded-full bg-white/10">
          <div
            className={`h-full rounded-full ${color} transition-all duration-700`}
            style={{ width: `${Math.max(pct, 2)}%` }}
          />
        </div>
      </div>
      <span className="w-10 font-[family-name:var(--font-mono)] text-xs font-semibold text-[var(--color-text)]">
        <AnimatedNumber value={pct} format={(n) => `${Math.round(n)}%`} duration={700} />
      </span>
    </div>
  );
}

function ModuleBadge({ module }: { module: string | null }) {
  const config: Record<string, { bg: string; text: string }> = {
    ESTIXE: { bg: "bg-teal-900/30", text: "text-teal-400" },
    NOMOS: { bg: "bg-sky-900/30", text: "text-sky-400" },
    METIS: { bg: "bg-violet-900/30", text: "text-violet-400" },
  };
  const c = module ? config[module] : { bg: "bg-white/10", text: "text-slate-400" };
  return (
    <span className={`shrink-0 rounded px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[10px] font-bold ${c.bg} ${c.text}`}>
      {module || "—"}
    </span>
  );
}

function DecisionBadge({ decision }: { decision: string }) {
  const config: Record<string, { bg: string; text: string; label: string }> = {
    bypass: { bg: "bg-teal-900/30", text: "text-teal-400", label: "Desviado" },
    route: { bg: "bg-blue-900/30", text: "text-blue-400", label: "Roteado" },
    block: { bg: "bg-red-900/30", text: "text-red-400", label: "Bloqueado" },
    fallback: { bg: "bg-amber-900/30", text: "text-amber-400", label: "Fallback" },
    error: { bg: "bg-red-500", text: "text-white", label: "Erro" },
  };
  const c = config[decision] || config.error;
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${c.bg} ${c.text}`}>
      {c.label}
    </span>
  );
}

function NemosRecommendationCard() {
  const [state, setState] = useState<"idle" | "confirming" | "applied" | "dismissed">("idle");

  if (state === "dismissed") return null;

  if (state === "applied") {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-green-700/40 bg-green-950/20 px-5 py-4">
        <Check className="h-4 w-4 shrink-0 text-green-400" />
        <p className="text-sm text-green-300">
          Recomendação aplicada — <code className="font-[family-name:var(--font-mono)]">limite_cartao_faq</code> migrado para{" "}
          <strong>gpt-4o-mini</strong>. Economia de <strong>R$ 12,40/dia</strong> ativa.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="flex items-start gap-4 rounded-xl border border-amber-700/40 bg-amber-950/20 p-5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-900/40">
          <Brain className="h-5 w-5 text-amber-400" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-amber-200">Recomendação NEMOS</p>
          <p className="mt-0.5 text-sm text-amber-300/80">
            Intent{" "}
            <code className="font-[family-name:var(--font-mono)] text-amber-200">limite_cartao_faq</code>{" "}
            pode migrar de <strong>gpt-4o → gpt-4o-mini</strong> com 97% de confiança. Economia estimada:{" "}
            <strong className="text-green-400">R$ 12,40/dia</strong>.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            onClick={() => setState("confirming")}
            className="flex items-center gap-1.5 rounded-lg bg-amber-800/40 px-3 py-1.5 text-xs font-medium text-amber-200 hover:bg-amber-800/60 transition-colors"
          >
            Aplicar
            <ChevronRight className="h-3 w-3" />
          </button>
          <button
            onClick={() => setState("dismissed")}
            className="rounded-lg px-3 py-1.5 text-xs font-medium text-amber-400/60 hover:text-amber-300 transition-colors"
          >
            Ignorar
          </button>
        </div>
      </div>

      {/* Confirmation modal */}
      {state === "confirming" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-2xl">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-900/40">
                  <Brain className="h-5 w-5 text-amber-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-text)]">Confirmar migração de modelo</h3>
                  <p className="text-xs text-[var(--color-text-muted)]">NEMOS — 97% de confiança</p>
                </div>
              </div>
              <button onClick={() => setState("idle")} className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Impact preview */}
            <div className="mt-5 rounded-xl bg-white/5 divide-y divide-[var(--color-border)]">
              <div className="flex justify-between px-4 py-3 text-sm">
                <span className="text-[var(--color-text-muted)]">Intent afetado</span>
                <code className="font-[family-name:var(--font-mono)] text-[var(--color-text)]">limite_cartao_faq</code>
              </div>
              <div className="flex justify-between px-4 py-3 text-sm">
                <span className="text-[var(--color-text-muted)]">Modelo atual</span>
                <span className="font-[family-name:var(--font-mono)] text-[var(--color-text)]">gpt-4o</span>
              </div>
              <div className="flex justify-between px-4 py-3 text-sm">
                <span className="text-[var(--color-text-muted)]">Novo modelo</span>
                <span className="font-[family-name:var(--font-mono)] text-[var(--color-primary)]">gpt-4o-mini</span>
              </div>
              <div className="flex justify-between px-4 py-3 text-sm">
                <span className="text-[var(--color-text-muted)]">Requests/dia afetados</span>
                <span className="text-[var(--color-text)]">~2.840</span>
              </div>
              <div className="flex justify-between px-4 py-3 text-sm">
                <span className="text-[var(--color-text-muted)]">Economia estimada</span>
                <span className="font-semibold text-green-400">R$ 12,40/dia · R$ 372/mês</span>
              </div>
              <div className="flex justify-between px-4 py-3 text-sm">
                <span className="text-[var(--color-text-muted)]">Qualidade esperada</span>
                <span className="text-green-400">≥ 97% de equivalência semântica</span>
              </div>
            </div>

            <p className="mt-4 text-xs text-[var(--color-text-muted)]">
              A mudança entra em vigor imediatamente. Pode ser revertida a qualquer momento na página de Roteamento.
            </p>

            <div className="mt-5 flex justify-end gap-3">
              <button
                onClick={() => setState("idle")}
                className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={() => setState("applied")}
                className="flex items-center gap-2 rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 transition-opacity"
              >
                <Check className="h-4 w-4" />
                Confirmar migração
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
