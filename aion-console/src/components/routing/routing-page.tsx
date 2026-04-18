"use client";

import { useState } from "react";
import {
  GitBranch,
  DollarSign,
  Sparkles,
  Clock,
  AlertTriangle,
  Plus,
  GripVertical,
  Trash2,
  TrendingDown,
  Gauge,
  ArrowRight,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { mockModels, mockModuleStats, mockDistribution } from "@/lib/mock-data";

const defaultRules = [
  { id: "r1", prompt_type: "Simples", model_id: "gpt-4o-mini", condition: "< 50 tokens" },
  { id: "r2", prompt_type: "Complexo", model_id: "gpt-4o", condition: "> 200 tokens" },
  { id: "r3", prompt_type: "Código", model_id: "claude-sonnet", condition: "Contém código" },
  { id: "r4", prompt_type: "Padrão", model_id: "gpt-4o-mini", condition: "—" },
];

const modelDistribution = [
  { model: "GPT-4o Mini", pct: 78, color: "bg-sky-500", cost: "$0.15/1M" },
  { model: "GPT-4o", pct: 14, color: "bg-violet-500", cost: "$2.50/1M" },
  { model: "Claude Sonnet", pct: 6, color: "bg-teal-500", cost: "$3.00/1M" },
  { model: "Gemini Flash", pct: 2, color: "bg-amber-500", cost: "$0.10/1M" },
];

export function RoutingPage() {
  const [priority, setPriority] = useState(50);
  const [maxLatency, setMaxLatency] = useState(3000);
  const [rules] = useState(defaultRules);
  const [fallbackChain] = useState(["gpt-4o-mini", "gpt-4o", "gemini-flash"]);
  const models = mockModels;
  const nomosStats = mockModuleStats.nomos;

  const statusBadge = (status: string) => {
    switch (status) {
      case "active": return <Badge variant="success">Ativo</Badge>;
      case "inactive": return <Badge variant="muted">Inativo</Badge>;
      case "fallback": return <Badge variant="warning">Apenas fallback</Badge>;
      default: return null;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          <span className="text-sky-600">NOMOS</span> — Roteamento
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          Inteligência de seleção de modelos. Cada decisão otimiza custo sem perder qualidade.
        </p>
      </div>

      {/* ═══ HERO — Impacto do NOMOS ═══ */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-sky-800/50 bg-gradient-to-br from-sky-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-sky-600">
            <GitBranch className="h-3.5 w-3.5" />
            Decisões hoje
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-sky-200">
            {nomosStats.decisions_today.toLocaleString("pt-BR")}
          </div>
          <div className="mt-0.5 text-xs text-sky-600">rotas selecionadas automaticamente</div>
        </div>
        <div className="rounded-xl border border-green-800/50 bg-gradient-to-br from-green-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-green-600">
            <DollarSign className="h-3.5 w-3.5" />
            Custo otimizado
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-green-400">
            R$ {nomosStats.cost_optimized.toFixed(2)}
          </div>
          <div className="mt-0.5 text-xs text-green-600">economizado pelo roteamento inteligente</div>
        </div>
        <div className="rounded-xl border border-sky-800/50 bg-gradient-to-br from-sky-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-sky-600">
            <TrendingDown className="h-3.5 w-3.5" />
            Rotas para modelo leve
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-sky-200">
            {((nomosStats.routes_to_light / nomosStats.decisions_today) * 100).toFixed(0)}%
          </div>
          <div className="mt-0.5 text-xs text-sky-600">{nomosStats.routes_to_light.toLocaleString("pt-BR")} chamadas para modelo barato</div>
        </div>
        <div className="rounded-xl border border-sky-800/50 bg-gradient-to-br from-sky-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-sky-600">
            <Zap className="h-3.5 w-3.5" />
            Tempo de decisão
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-sky-200">
            {nomosStats.avg_decision_ms}ms
          </div>
          <div className="mt-0.5 text-xs text-sky-600">latência média do roteamento</div>
        </div>
      </div>

      {/* ═══ Distribuição de modelos — onde o NOMOS manda ═══ */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
          <Gauge className="h-4 w-4 text-sky-600" />
          Distribuição de modelos
        </h2>
        <p className="mb-4 text-xs text-[var(--color-text-muted)]">
          Como o NOMOS está distribuindo as chamadas entre modelos hoje.
        </p>

        {/* Stacked bar */}
        <div className="mb-4 flex h-6 overflow-hidden rounded-full">
          {modelDistribution.map((m) => (
            <div
              key={m.model}
              className={`${m.color} transition-all duration-300`}
              style={{ width: `${m.pct}%` }}
              title={`${m.model}: ${m.pct}%`}
            />
          ))}
        </div>

        {/* Legend */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {modelDistribution.map((m) => (
            <div key={m.model} className="flex items-center gap-2">
              <div className={`h-2.5 w-2.5 rounded-full ${m.color}`} />
              <div>
                <div className="text-xs font-medium text-[var(--color-text)]">
                  {m.model} <span className="font-[family-name:var(--font-mono)] font-bold">{m.pct}%</span>
                </div>
                <div className="font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-text-muted)]">{m.cost}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Priority slider — with impact context */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <h2 className="mb-1 text-sm font-semibold text-[var(--color-text)]">Prioridade de decisão</h2>
        <p className="mb-4 text-xs text-[var(--color-text-muted)]">
          Define como o NOMOS escolhe entre modelos. Mais à esquerda = mais barato. Mais à direita = mais inteligente.
        </p>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 text-sm text-green-600">
            <DollarSign className="h-4 w-4" />
            Custo
          </div>
          <div className="relative flex-1">
            <div className="h-2 rounded-full bg-gradient-to-r from-green-200 via-slate-200 to-violet-200" />
            <input
              type="range"
              min={0}
              max={100}
              value={priority}
              onChange={(e) => setPriority(Number(e.target.value))}
              className="absolute inset-0 h-2 w-full cursor-pointer appearance-none bg-transparent [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-primary)] [&::-webkit-slider-thumb]:shadow-md"
              aria-label="Prioridade custo vs qualidade"
            />
          </div>
          <div className="flex items-center gap-1 text-sm text-violet-600">
            <Sparkles className="h-4 w-4" />
            Qualidade
          </div>
        </div>
        {priority < 30 && (
          <div className="mt-3 flex items-center gap-1.5 text-xs text-green-600">
            <TrendingDown className="h-3.5 w-3.5" />
            Modo econômico — NOMOS vai priorizar modelos leves sempre que possível.
          </div>
        )}
        {priority > 70 && (
          <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-600">
            <AlertTriangle className="h-3.5 w-3.5" />
            Modo qualidade — custo estimado pode aumentar ~{((priority - 50) * 1.2).toFixed(0)}%.
          </div>
        )}
      </div>

      {/* Models — with usage context */}
      <div>
        <h2 className="mb-3 text-sm font-semibold text-[var(--color-text)]">Modelos disponíveis</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {models.map((model) => {
            const dist = modelDistribution.find((m) => m.model === model.name);
            return (
              <div
                key={model.id}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 transition-shadow hover:shadow-md"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-[family-name:var(--font-mono)] text-sm font-semibold text-[var(--color-text)]">
                      {model.name}
                    </div>
                    <div className="text-xs text-[var(--color-text-muted)]">{model.provider}</div>
                  </div>
                  {statusBadge(model.status)}
                </div>
                {/* Usage indicator */}
                {dist && (
                  <div className="mt-2 flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
                      <div className={`h-full rounded-full ${dist.color}`} style={{ width: `${dist.pct}%` }} />
                    </div>
                    <span className="font-[family-name:var(--font-mono)] text-xs font-bold text-[var(--color-text)]">{dist.pct}%</span>
                  </div>
                )}
                <div className="mt-3 space-y-1.5 text-xs text-[var(--color-text-muted)]">
                  <div className="flex justify-between">
                    <span>Entrada</span>
                    <span className="font-[family-name:var(--font-mono)]">${model.cost_input_per_1m}/1M</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Saída</span>
                    <span className="font-[family-name:var(--font-mono)]">${model.cost_output_per_1m}/1M</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Latência</span>
                    <span className="font-[family-name:var(--font-mono)]">{model.latency_ms}ms</span>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1">
                  {model.capabilities.map((cap) => (
                    <Badge key={cap} variant="muted">{cap}</Badge>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Rules Table */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-6 py-4">
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Regras de roteamento</h2>
            <p className="text-xs text-[var(--color-text-muted)]">Quando o NOMOS encontra um padrão, aplica a regra automaticamente.</p>
          </div>
          <button
            disabled
            title="Configuração de regras customizadas disponível em breve"
            className="flex items-center gap-1.5 rounded-lg bg-[var(--color-cta)]/50 px-3 py-1.5 text-xs font-semibold text-white/60 cursor-not-allowed"
          >
            <Plus className="h-3.5 w-3.5" />
            Adicionar regra
          </button>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-white/5 text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
              <th className="px-6 py-3">Tipo</th>
              <th className="px-6 py-3">Modelo</th>
              <th className="px-6 py-3">Condição</th>
              <th className="w-12 px-6 py-3" />
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-white/5">
                <td className="px-6 py-3 text-sm font-medium text-[var(--color-text)]">{rule.prompt_type}</td>
                <td className="px-6 py-3 font-[family-name:var(--font-mono)] text-sm text-sky-600">{rule.model_id}</td>
                <td className="px-6 py-3 text-sm text-[var(--color-text-muted)]">{rule.condition}</td>
                <td className="px-6 py-3">
                  {rule.prompt_type !== "Padrão" && (
                    <button
                      disabled
                      title="Remoção de regras disponível em breve"
                      className="text-[var(--color-text-muted)]/40 cursor-not-allowed"
                      aria-label="Remover regra (em breve)"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Fallback Chain — with decision path visualization */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Cadeia de fallback</h2>
            <p className="text-xs text-[var(--color-text-muted)]">
              Se o modelo principal falhar, o NOMOS tenta o próximo. Hoje: {mockDistribution.fallback_pct}% das chamadas usaram fallback.
            </p>
          </div>
          <button
            disabled
            title="Edição da cadeia de fallback disponível em breve"
            className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)]/50 px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)]/50 cursor-not-allowed"
          >
            <Plus className="h-3.5 w-3.5" />
            Adicionar fallback
          </button>
        </div>
        <div className="flex items-center gap-3">
          {fallbackChain.map((modelId, i) => (
            <div key={modelId} className="flex items-center gap-3">
              <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2">
                <GripVertical className="h-3.5 w-3.5 cursor-grab text-[var(--color-text-muted)]" />
                <span className="text-xs font-medium text-[var(--color-text-muted)]">{i + 1}.</span>
                <span className="font-[family-name:var(--font-mono)] text-sm font-medium text-[var(--color-text)]">{modelId}</span>
              </div>
              {i < fallbackChain.length - 1 && (
                <ArrowRight className="h-4 w-4 text-[var(--color-text-muted)]" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Max Latency — with impact context */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Latência máxima</h2>
            <p className="text-xs text-[var(--color-text-muted)]">Tempo máximo antes de acionar fallback. Reduzir demais pode aumentar o uso de fallback.</p>
          </div>
          <span className="font-[family-name:var(--font-mono)] text-lg font-bold text-sky-600">
            {maxLatency >= 1000 ? `${(maxLatency / 1000).toFixed(1)}s` : `${maxLatency}ms`}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Clock className="h-4 w-4 text-green-600" />
          <input
            type="range"
            min={500}
            max={30000}
            step={500}
            value={maxLatency}
            onChange={(e) => setMaxLatency(Number(e.target.value))}
            className="h-2 flex-1 cursor-pointer appearance-none rounded-full bg-white/15 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-sky-600 [&::-webkit-slider-thumb]:shadow-md"
            aria-label="Latência máxima"
          />
          <AlertTriangle className="h-4 w-4 text-amber-500" />
        </div>
        {maxLatency < 1500 && (
          <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-600">
            <AlertTriangle className="h-3.5 w-3.5" />
            Limite agressivo — modelos premium podem não responder a tempo, aumentando fallbacks.
          </div>
        )}
      </div>
    </div>
  );
}
