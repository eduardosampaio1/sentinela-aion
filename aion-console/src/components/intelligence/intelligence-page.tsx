"use client";

import { useState } from "react";
import {
  Brain,
  Shield,
  TrendingDown,
  Zap,
  AlertTriangle,
  Activity,
  ChevronRight,
  RefreshCw,
  Target,
  GitBranch,
  Layers,
  Eye,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/demo-banner";
import { useApiData } from "@/lib/use-api-data";
import { getIntelligenceOverview, getThreats, getIntelligenceIntents, getGlobalThreatFeed } from "@/lib/api";

// ─── Mock fallbacks ────────────────────────────────────────────────────────────

const mockOverview = {
  security: { requests_blocked: 1240, pii_intercepted: 89, top_block_reason: "policy_violation" },
  economics: {
    total_spend_usd: 142.8,
    estimated_without_aion_usd: 268.4,
    savings_usd: 125.6,
    savings_pct: 46.8,
    tokens_saved: 4812000,
    top_model_used: "gpt-4o-mini",
  },
  intelligence: {
    requests_processed: 847240,
    bypass_rate: 0.684,
    avg_latency_ms: 312,
    module_maturity: {
      estixe: { level: "stable", decisions: 847240 },
      nomos: { level: "stable", decisions: 267530 },
      metis: { level: "learning", decisions: 241600 },
    },
  },
  budget: null,
};

const mockThreats: Record<string, unknown>[] = [
  {
    session_id: "sess-a1b2",
    tenant: "default",
    pattern: "progressive_bypass",
    confidence: 0.87,
    detected_at: Date.now() / 1000 - 1800,
    turns_analyzed: 4,
    recommended_action: "escalate_threshold",
  },
  {
    session_id: "sess-c3d4",
    tenant: "default",
    pattern: "authority_escalation",
    confidence: 0.85,
    detected_at: Date.now() / 1000 - 5400,
    turns_analyzed: 3,
    recommended_action: "block_session",
  },
];

const mockIntents: Record<string, unknown>[] = [
  { intent: "code_generation", requests: 18420, bypass_rate: 0.91, avg_complexity: 72.4 },
  { intent: "data_analysis", requests: 12850, bypass_rate: 0.88, avg_complexity: 65.1 },
  { intent: "document_summary", requests: 9340, bypass_rate: 0.95, avg_complexity: 41.3 },
  { intent: "question_answering", requests: 7610, bypass_rate: 0.93, avg_complexity: 38.7 },
  { intent: "translation", requests: 5240, bypass_rate: 0.97, avg_complexity: 29.2 },
];

// ─── Helpers ───────────────────────────────────────────────────────────────────

const PATTERN_LABELS: Record<string, { label: string; color: string }> = {
  progressive_bypass: { label: "Bypass Progressivo", color: "bg-orange-900/30 text-orange-400 border-orange-800/50" },
  intent_mutation: { label: "Mutação de Intent", color: "bg-red-900/30 text-red-400 border-red-800/50" },
  authority_escalation: { label: "Escalada de Autoridade", color: "bg-purple-900/30 text-purple-400 border-purple-800/50" },
  threshold_probing: { label: "Sondagem de Limiar", color: "bg-yellow-900/30 text-yellow-400 border-yellow-800/50" },
};

const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  monitor: { label: "Monitorar", color: "text-blue-400" },
  escalate_threshold: { label: "Elevar limiar", color: "text-orange-400" },
  block_session: { label: "Bloquear sessão", color: "text-red-400" },
};

const MATURITY_CONFIG: Record<string, { label: string; color: string; bar: string }> = {
  learning: { label: "Aprendendo", color: "text-amber-400", bar: "bg-amber-500" },
  stable: { label: "Estável", color: "text-teal-400", bar: "bg-teal-500" },
  optimized: { label: "Otimizado", color: "text-green-400", bar: "bg-green-500" },
};

function fmtTime(ts: number): string {
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 60) return "agora";
  if (diff < 3600) return `${Math.floor(diff / 60)}m atrás`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h atrás`;
  return `${Math.floor(diff / 86400)}d atrás`;
}

function fmt(n: number, decimals = 0): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toFixed(decimals);
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  sub,
  icon,
  accent,
}: {
  label: string;
  value: string;
  sub: string;
  icon: React.ReactNode;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--color-text-muted)]">{label}</p>
        <span className="text-[var(--color-text-muted)] opacity-50">{icon}</span>
      </div>
      <p className={`mt-2 text-2xl font-bold ${accent ?? "text-[var(--color-text)]"}`}>{value}</p>
      <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">{sub}</p>
    </div>
  );
}

function ModuleMaturityCard({
  name,
  icon,
  maturity,
  decisions,
}: {
  name: string;
  icon: React.ReactNode;
  maturity: string;
  decisions: number;
}) {
  const cfg = MATURITY_CONFIG[maturity] ?? MATURITY_CONFIG.learning;
  const pct = maturity === "optimized" ? 100 : maturity === "stable" ? 70 : 35;
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/5 text-[var(--color-text-muted)]">
          {icon}
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--color-text)]">{name}</p>
          <p className={`text-xs font-medium ${cfg.color}`}>{cfg.label}</p>
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-white/10">
        <div
          className={`h-1.5 rounded-full transition-all ${cfg.bar}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-[var(--color-text-muted)]">
        {fmt(decisions)} decisões registradas
      </p>
    </div>
  );
}

function ThreatCard({ threat }: { threat: Record<string, unknown> }) {
  const pattern = threat.pattern as string;
  const action = threat.recommended_action as string;
  const confidence = (threat.confidence as number) * 100;
  const patternCfg = PATTERN_LABELS[pattern] ?? { label: pattern, color: "" };
  const actionCfg = ACTION_LABELS[action] ?? { label: action, color: "text-[var(--color-text)]" };

  return (
    <div className="flex items-start gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-red-900/20 text-red-400">
        <AlertTriangle className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <span
            className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${patternCfg.color}`}
          >
            {patternCfg.label}
          </span>
          <span className="text-xs text-[var(--color-text-muted)]">
            {threat.turns_analyzed as number} turnos · confiança {confidence.toFixed(0)}%
          </span>
        </div>
        <p className="text-xs text-[var(--color-text-muted)] font-mono truncate">
          sessão: {threat.session_id as string}
        </p>
        <div className="mt-2 flex items-center justify-between">
          <span className={`text-xs font-medium ${actionCfg.color}`}>
            → {actionCfg.label}
          </span>
          <span className="text-xs text-[var(--color-text-muted)]">
            {fmtTime(threat.detected_at as number)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export function IntelligencePage() {
  const [activeTab, setActiveTab] = useState<"overview" | "threats" | "intents" | "global">("overview");

  const {
    data: overview,
    isDemo: overviewIsDemo,
    refetch: refetchOverview,
  } = useApiData(
    () => getIntelligenceOverview(30),
    mockOverview as Record<string, unknown>,
    { intervalMs: 60_000 },
  );

  const {
    data: threats,
    isDemo: threatsIsDemo,
    refetch: refetchThreats,
  } = useApiData(getThreats, mockThreats, {
    intervalMs: activeTab === "threats" ? 30_000 : undefined,
  });

  const {
    data: intents,
    isDemo: intentsIsDemo,
    refetch: refetchIntents,
  } = useApiData(getIntelligenceIntents, mockIntents, {
    intervalMs: activeTab === "intents" ? 60_000 : undefined,
  });

  const {
    data: globalFeed,
    isDemo: globalIsDemo,
    refetch: refetchGlobal,
  } = useApiData(
    () => getGlobalThreatFeed(undefined, 30),
    [] as Record<string, unknown>[],
    { intervalMs: activeTab === "global" ? 120_000 : undefined },
  );

  const sec = (overview.security ?? {}) as Record<string, unknown>;
  const econ = (overview.economics ?? {}) as Record<string, unknown>;
  const intel = (overview.intelligence ?? {}) as Record<string, unknown>;
  const maturity = (intel.module_maturity ?? {}) as Record<string, Record<string, unknown>>;
  const isDemo = overviewIsDemo || threatsIsDemo || intentsIsDemo || globalIsDemo;
  const refetch = () => { refetchOverview(); refetchThreats(); refetchIntents(); refetchGlobal(); };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            Inteligência
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            O que o AION aprendeu sobre o seu ambiente — dados reais do NEMOS
          </p>
        </div>
        <button
          onClick={refetch}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Atualizar
        </button>
      </div>

      {isDemo && <DemoBanner onRetry={refetch} />}

      {/* Hero metrics */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="Economia gerada"
          value={`$${fmt(((econ.savings_usd as number) ?? 0), 0)}`}
          sub={`${((econ.savings_pct as number) ?? 0).toFixed(1)}% de redução vs. sem AION`}
          icon={<TrendingDown className="h-4 w-4" />}
          accent="text-teal-400"
        />
        <MetricCard
          label="Tokens poupados"
          value={fmt((econ.tokens_saved as number) ?? 0)}
          sub="compressão + cache semântico"
          icon={<Zap className="h-4 w-4" />}
          accent="text-sky-400"
        />
        <MetricCard
          label="Requests bloqueados"
          value={fmt((sec.requests_blocked as number) ?? 0)}
          sub={`motivo: ${(sec.top_block_reason as string)?.replace(/_/g, " ") ?? "—"}`}
          icon={<Shield className="h-4 w-4" />}
          accent="text-red-400"
        />
        <MetricCard
          label="PIIs interceptados"
          value={fmt((sec.pii_intercepted as number) ?? 0)}
          sub="não chegaram ao LLM"
          icon={<Eye className="h-4 w-4" />}
          accent="text-amber-400"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--color-border)]">
        {(
          [
            { id: "overview", label: "Aprendizado dos Módulos", icon: <Brain className="h-3.5 w-3.5" /> },
            {
              id: "threats",
              label: "Ameaças Ativas",
              icon: <AlertTriangle className="h-3.5 w-3.5" />,
              badge: threats.length > 0 ? threats.length : undefined,
            },
            { id: "intents", label: "Intents Aprendidos", icon: <Target className="h-3.5 w-3.5" /> },
            { id: "global", label: "Feed Global", icon: <Activity className="h-3.5 w-3.5" /> },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab.id
                ? "border-[var(--color-primary)] text-[var(--color-primary)]"
                : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tab.icon}
            {tab.label}
            {"badge" in tab && tab.badge !== undefined && (
              <span className="ml-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab: Module Learning */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Module maturity */}
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              {
                name: "ESTIXE",
                icon: <Shield className="h-5 w-5" />,
                key: "estixe",
                defaultMaturity: "stable",
                defaultDecisions: 847240,
              },
              {
                name: "NOMOS",
                icon: <GitBranch className="h-5 w-5" />,
                key: "nomos",
                defaultMaturity: "stable",
                defaultDecisions: 267530,
              },
              {
                name: "METIS",
                icon: <Layers className="h-5 w-5" />,
                key: "metis",
                defaultMaturity: "learning",
                defaultDecisions: 241600,
              },
            ].map((mod) => {
              const m = maturity[mod.key] ?? {};
              return (
                <ModuleMaturityCard
                  key={mod.key}
                  name={mod.name}
                  icon={mod.icon}
                  maturity={(m.level as string) ?? mod.defaultMaturity}
                  decisions={(m.decisions as number) ?? mod.defaultDecisions}
                />
              );
            })}
          </div>

          {/* Key stats grid */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
              <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                Eficiência de roteamento
              </p>
              <div className="space-y-2">
                {[
                  { label: "Taxa de bypass", value: `${(((intel.bypass_rate as number) ?? 0.684) * 100).toFixed(1)}%`, color: "text-teal-400" },
                  { label: "Latência média", value: `${((intel.avg_latency_ms as number) ?? 312).toFixed(0)}ms`, color: "text-sky-400" },
                  { label: "Modelo top", value: (econ.top_model_used as string) ?? "gpt-4o-mini", color: "text-[var(--color-text)]" },
                ].map((row) => (
                  <div key={row.label} className="flex items-center justify-between">
                    <span className="text-sm text-[var(--color-text-muted)]">{row.label}</span>
                    <span className={`text-sm font-semibold ${row.color}`}>{row.value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
              <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                Segurança
              </p>
              <div className="space-y-2">
                {[
                  { label: "Requisições bloqueadas", value: fmt((sec.requests_blocked as number) ?? 0), color: "text-red-400" },
                  { label: "PIIs interceptados", value: fmt((sec.pii_intercepted as number) ?? 0), color: "text-amber-400" },
                  { label: "Principal motivo de bloco", value: (sec.top_block_reason as string)?.replace(/_/g, " ") ?? "—", color: "text-[var(--color-text)]" },
                ].map((row) => (
                  <div key={row.label} className="flex items-center justify-between">
                    <span className="text-sm text-[var(--color-text-muted)]">{row.label}</span>
                    <span className={`text-sm font-semibold ${row.color}`}>{row.value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
              <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                Economia
              </p>
              <div className="space-y-2">
                {[
                  { label: "Gasto total", value: `$${((econ.total_spend_usd as number) ?? 0).toFixed(2)}`, color: "text-[var(--color-text)]" },
                  { label: "Sem AION (estimado)", value: `$${((econ.estimated_without_aion_usd as number) ?? 0).toFixed(2)}`, color: "text-[var(--color-text-muted)]" },
                  { label: "Economia", value: `$${((econ.savings_usd as number) ?? 0).toFixed(2)} (${((econ.savings_pct as number) ?? 0).toFixed(1)}%)`, color: "text-teal-400" },
                ].map((row) => (
                  <div key={row.label} className="flex items-center justify-between">
                    <span className="text-sm text-[var(--color-text-muted)]">{row.label}</span>
                    <span className={`text-sm font-semibold ${row.color}`}>{row.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Active Threats */}
      {activeTab === "threats" && (
        <div className="space-y-4">
          {threats.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-16">
              <Shield className="mb-3 h-10 w-10 text-teal-400 opacity-60" />
              <p className="text-sm font-medium text-[var(--color-text)]">Nenhuma ameaça ativa</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                O detector multi-turn não encontrou padrões suspeitos nas últimas 24h
              </p>
            </div>
          ) : (
            <>
              <p className="text-xs text-[var(--color-text-muted)]">
                {threats.length} sinal{threats.length !== 1 ? "is" : ""} de ameaça ativo{threats.length !== 1 ? "s" : ""} · atualizado automaticamente
              </p>
              <div className="space-y-3">
                {threats.map((t, i) => (
                  <ThreatCard key={(t.session_id as string) ?? i} threat={t} />
                ))}
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-amber-900/10 p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5 text-amber-400" />
                  <div>
                    <p className="text-sm font-medium text-amber-400">Sobre o detector de ameaças</p>
                    <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                      O AION analisa padrões de risco <strong>entre turnos</strong> de uma mesma sessão.
                      Sinais são gerados quando um padrão de ataque multi-turno é identificado —
                      cada turno individualmente pode parecer inofensivo.
                    </p>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Tab: Learned Intents */}
      {activeTab === "intents" && (
        <div className="space-y-4">
          {intents.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-16">
              <Activity className="mb-3 h-10 w-10 text-[var(--color-text-muted)] opacity-40" />
              <p className="text-sm font-medium text-[var(--color-text)]">Sem dados de intent ainda</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                Os intents aparecem aqui conforme o NEMOS registra decisões
              </p>
            </div>
          ) : (
            <>
              <p className="text-xs text-[var(--color-text-muted)]">
                {intents.length} padrões de intent detectados e aprendidos pelo NEMOS
              </p>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-border)]">
                      {["Intent", "Requisições", "Taxa bypass", "Complexidade média"].map((h) => (
                        <th
                          key={h}
                          className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {intents.map((intent, i) => {
                      const bypassRate = ((intent.bypass_rate as number) ?? 0) * 100;
                      const complexity = (intent.avg_complexity as number) ?? 0;
                      return (
                        <tr
                          key={(intent.intent as string) ?? i}
                          className="border-b border-[var(--color-border)]/50 last:border-0 hover:bg-white/2"
                        >
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <ChevronRight className="h-3 w-3 text-[var(--color-text-muted)]" />
                              <span className="font-mono text-xs text-[var(--color-text)]">
                                {(intent.intent as string) ?? "—"}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-[var(--color-text-muted)]">
                            {fmt((intent.requests as number) ?? 0)}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 w-16 rounded-full bg-white/10">
                                <div
                                  className="h-1.5 rounded-full bg-teal-500"
                                  style={{ width: `${bypassRate}%` }}
                                />
                              </div>
                              <span className="text-xs text-teal-400">{bypassRate.toFixed(0)}%</span>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`text-xs font-medium ${
                                complexity > 60
                                  ? "text-orange-400"
                                  : complexity > 40
                                  ? "text-yellow-400"
                                  : "text-green-400"
                              }`}
                            >
                              {complexity.toFixed(0)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-sky-900/10 p-4">
                <div className="flex items-start gap-3">
                  <Brain className="h-4 w-4 flex-shrink-0 mt-0.5 text-sky-400" />
                  <div>
                    <p className="text-sm font-medium text-sky-400">Lock-in por dados acumulados</p>
                    <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                      Cada intent aprendido representa horas de calibração acumulada.
                      O NEMOS usa esses padrões para melhorar o roteamento e reduzir custo
                      progressivamente — quanto mais dados, maior a precisão.
                    </p>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Tab: Global Threat Feed (T3.3) */}
      {activeTab === "global" && (
        <div className="space-y-4">
          {globalIsDemo && <DemoBanner onRetry={refetchGlobal} />}

          <div className="rounded-xl border border-sky-800/40 bg-sky-900/10 p-4">
            <div className="flex items-start gap-3">
              <Activity className="h-4 w-4 flex-shrink-0 mt-0.5 text-sky-400" />
              <div>
                <p className="text-sm font-medium text-sky-400">Feed de ameaças cross-tenant (k-anônimo)</p>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  Sinais agregados de múltiplos tenants com k-anonimidade.
                  Configure <code className="text-sky-300">AION_CONTRIBUTE_GLOBAL_LEARNING=true</code> para
                  contribuir e receber sinais globais. Nenhum conteúdo de mensagem é compartilhado — apenas
                  vetores de features anonimizados.
                </p>
              </div>
            </div>
          </div>

          {globalFeed.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-16">
              <Activity className="mb-3 h-10 w-10 text-[var(--color-text-muted)] opacity-40" />
              <p className="text-sm font-medium text-[var(--color-text)]">Feed global indisponível</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                Ative <code>AION_CONTRIBUTE_GLOBAL_LEARNING=true</code> para acessar
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-border)]">
                    {["Categoria", "Score de risco", "Tenants observados", "Confiança"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {globalFeed.map((signal, i) => (
                    <tr key={i} className="border-b border-[var(--color-border)]/50 last:border-0 hover:bg-white/2">
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-[var(--color-text)]">
                          {(signal.category as string) ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-medium ${
                          ((signal.avg_risk as number) ?? 0) > 0.7 ? "text-red-400" : "text-amber-400"
                        }`}>
                          {(((signal.avg_risk as number) ?? 0) * 100).toFixed(0)}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-[var(--color-text-muted)]">
                        {(signal.tenant_count as number) ?? "≥5"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 rounded-full bg-white/10">
                            <div
                              className="h-1.5 rounded-full bg-sky-500"
                              style={{ width: `${(((signal.confidence as number) ?? 0.5) * 100)}%` }}
                            />
                          </div>
                          <span className="text-xs text-sky-400">
                            {((((signal.confidence as number) ?? 0.5) * 100).toFixed(0))}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
