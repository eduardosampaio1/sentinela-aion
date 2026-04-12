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
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { useRealtimeStats } from "@/lib/use-realtime";
import { mockEvents } from "@/lib/mock-data";
import type { ServiceStatus } from "@/lib/types";

const fmtBRL = (n: number) => `R$ ${n.toFixed(2)}`;
const fmtPct = (n: number) => `${Math.round(n)}%`;
const fmtInt = (n: number) => Math.round(n).toLocaleString("pt-BR");

export function StatusPage() {
  const [status] = useState<ServiceStatus>("online");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const { stats, modules, distribution: dist, operational: opState } = useRealtimeStats(3000, autoRefresh);

  const recentEvents = mockEvents.slice(0, 5);

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
            Uptime: <strong className="text-[var(--color-text)]">{opState.uptime_hours}h</strong>
          </span>
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
            <strong className="font-[family-name:var(--font-mono)] text-[var(--color-text)]">{stats.errors}</strong>
            <span className="text-xs text-[var(--color-text-muted)]"> ({((stats.errors / stats.total_requests) * 100).toFixed(1)}%)</span>
          </div>
        </div>
        {mockEvents.some((e) => e.decision === "fallback") && (
          <div className="flex items-center gap-1.5 text-xs text-amber-600">
            <AlertTriangle className="h-3.5 w-3.5" />
            {mockEvents.filter((e) => e.decision === "fallback").length} fallback(s) recente(s)
          </div>
        )}
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
        {pct}%
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
