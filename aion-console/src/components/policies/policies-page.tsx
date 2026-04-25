"use client";

import { useState, useMemo, useEffect } from "react";
import {
  Save,
  RotateCcw,
  Sparkles,
  TrendingDown,
  TrendingUp,
  AlertTriangle,
  Info,
} from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { mockBehavior, estimateDialImpact } from "@/lib/mock-data";
import { setBehavior, resetBehavior, getBehavior } from "@/lib/api";
import type { BehaviorDial } from "@/lib/types";

const presets = [
  {
    id: "direct",
    label: "Direto e econômico",
    desc: "Custo mínimo. Respostas curtas. Ideal para operação e FAQ.",
    impact: "~40% menos tokens",
    values: { objectivity: 90, verbosity: 20, economy: 90, explanation: 10, confidence: 50, safe_mode: 50, formality: 40 },
  },
  {
    id: "explain",
    label: "Explica mais",
    desc: "Contexto completo. Ideal para onboarding e decisões críticas.",
    impact: "~60% mais tokens",
    values: { objectivity: 30, verbosity: 80, economy: 30, explanation: 90, confidence: 60, safe_mode: 60, formality: 60 },
  },
  {
    id: "balanced",
    label: "Equilibrado",
    desc: "Meio-termo entre custo e qualidade. Padrão recomendado.",
    impact: "Baseline",
    values: { objectivity: 50, verbosity: 50, economy: 50, explanation: 50, confidence: 50, safe_mode: 50, formality: 50 },
  },
];

const dialKeys: { key: keyof BehaviorDial; label: string; desc: string; low: string; high: string; tooltip: string }[] = [
  { key: "objectivity", label: "Objetividade", desc: "Quão direto a IA deve ser nas respostas.", low: "Contextualiza mais", high: "Vai direto ao ponto", tooltip: "Controla o nível de contexto nas respostas." },
  { key: "verbosity", label: "Verbosidade", desc: "Quanto detalhe a IA inclui na resposta.", low: "Conciso", high: "Detalhado", tooltip: "Menos verboso = menos tokens = menor custo." },
  { key: "economy", label: "Modo econômico", desc: "Prioriza custo menor ou qualidade maior.", low: "Qualidade máxima", high: "Custo mínimo", tooltip: "Quando alto, o AION prioriza modelos mais baratos e respostas mais curtas." },
  { key: "explanation", label: "Nível de explicação", desc: "Quanto a IA explica o raciocínio.", low: "Só a resposta", high: "Passo a passo", tooltip: "Mais explicação para equipes novas, menos para especialistas." },
  { key: "confidence", label: "Confiança mínima", desc: "Certeza necessária para a IA responder.", low: "Aceita incertas", high: "Só alta certeza", tooltip: "Confiança baixa: AION pode pedir mais informações." },
  { key: "safe_mode", label: "Modo seguro", desc: "Nível de conservadorismo da IA.", low: "Mais flexível", high: "Mais conservador", tooltip: "Conservador: evita ambiguidades e bloqueia conteúdo sensível." },
  { key: "formality", label: "Formalidade", desc: "Tom de comunicação da IA.", low: "Informal", high: "Formal", tooltip: "De casual e próximo a corporativo e formal." },
];

function riskColor(risk: string) {
  switch (risk) {
    case "high": return "text-red-600";
    case "medium": return "text-amber-600";
    case "low": return "text-blue-600";
    default: return "text-green-600";
  }
}

function riskLabel(risk: string) {
  switch (risk) {
    case "high": return "Alto";
    case "medium": return "Médio";
    case "low": return "Baixo";
    default: return "Nenhum";
  }
}

export function PoliciesPage() {
  const [dial, setDial] = useState<BehaviorDial>({ ...mockBehavior });
  const [activePreset, setActivePreset] = useState<string | null>(null);

  // Load real behavior from backend on mount; silently keep mock defaults on failure.
  useEffect(() => {
    getBehavior()
      .then((raw) => setDial((prev) => ({ ...prev, ...raw })))
      .catch(() => { /* backend unavailable — mock defaults remain */ });
  }, []);
  const [hasChanges, setHasChanges] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const impacts = useMemo(() => estimateDialImpact(dial), [dial]);

  // Aggregate impact
  const totalTokenChange = useMemo(() => {
    return Object.values(impacts).reduce((sum, i) => sum + i.token_change_pct, 0);
  }, [impacts]);

  const totalCostChange = useMemo(() => {
    return Object.values(impacts).reduce((sum, i) => sum + i.cost_change_pct, 0);
  }, [impacts]);

  const maxRisk = useMemo(() => {
    const risks = Object.values(impacts).map((i) => i.quality_risk);
    if (risks.includes("high")) return "high";
    if (risks.includes("medium")) return "medium";
    if (risks.includes("low")) return "low";
    return "none";
  }, [impacts]);

  const updateDial = (key: keyof BehaviorDial, value: number) => {
    setDial((prev) => ({ ...prev, [key]: value }));
    setActivePreset("custom");
    setHasChanges(true);
  };

  const applyPreset = (preset: typeof presets[number]) => {
    setDial(preset.values as BehaviorDial);
    setActivePreset(preset.id);
    setHasChanges(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await setBehavior(dial);
      setShowConfirm(false);
      setHasChanges(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await resetBehavior();
      setDial({ objectivity: 50, verbosity: 50, economy: 50, explanation: 50, confidence: 50, safe_mode: 50, formality: 50 });
      setActivePreset("balanced");
      setHasChanges(false);
    } catch {
      // Reset local even if API fails
      setDial({ objectivity: 50, verbosity: 50, economy: 50, explanation: 50, confidence: 50, safe_mode: 50, formality: 50 });
      setActivePreset("balanced");
      setHasChanges(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          Comportamento da IA
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          Cada ajuste mostra o impacto estimado em custo, tokens e risco.
        </p>
      </div>

      {/* Aggregate Impact Banner */}
      <div className="flex items-center gap-6 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-4">
        <div className="flex items-center gap-2 text-sm">
          {totalTokenChange < 0 ? (
            <TrendingDown className="h-4 w-4 text-green-600" />
          ) : totalTokenChange > 0 ? (
            <TrendingUp className="h-4 w-4 text-amber-600" />
          ) : (
            <Info className="h-4 w-4 text-[var(--color-text-muted)]" />
          )}
          <span className="text-[var(--color-text-muted)]">Tokens:</span>
          <strong className={`font-[family-name:var(--font-mono)] ${totalTokenChange < 0 ? "text-green-600" : totalTokenChange > 0 ? "text-amber-600" : "text-[var(--color-text)]"}`}>
            {totalTokenChange > 0 ? "+" : ""}{totalTokenChange.toFixed(0)}%
          </strong>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-[var(--color-text-muted)]">Custo:</span>
          <strong className={`font-[family-name:var(--font-mono)] ${totalCostChange < 0 ? "text-green-600" : totalCostChange > 0 ? "text-amber-600" : "text-[var(--color-text)]"}`}>
            {totalCostChange > 0 ? "+" : ""}{totalCostChange.toFixed(0)}%
          </strong>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-[var(--color-text-muted)]">Risco:</span>
          <strong className={riskColor(maxRisk)}>{riskLabel(maxRisk)}</strong>
        </div>
      </div>

      {/* Presets */}
      <div>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
          <Sparkles className="h-4 w-4 text-[var(--color-secondary)]" />
          Perfis rápidos
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {presets.map((preset) => (
            <button
              key={preset.id}
              onClick={() => applyPreset(preset)}
              className={`cursor-pointer rounded-xl border p-4 text-left transition-all duration-150 ${
                activePreset === preset.id
                  ? "border-[var(--color-primary)] bg-[var(--color-primary)]/5 shadow-sm"
                  : "border-[var(--color-border)] bg-[var(--color-surface)] hover:border-[var(--color-primary)]/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-[var(--color-text)]">{preset.label}</div>
                <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--color-primary)]">{preset.impact}</span>
              </div>
              <div className="mt-1 text-xs text-[var(--color-text-muted)]">{preset.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Dials with Impact */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        {activePreset === "custom" && (
          <div className="mb-4">
            <Badge variant="info">Personalizado</Badge>
          </div>
        )}

        <div className="divide-y divide-[var(--color-border)]">
          {dialKeys.map((d) => {
            const impact = impacts[d.key];
            return (
              <div key={d.key} className="py-2">
                <Slider
                  label={d.label}
                  description={d.desc}
                  lowLabel={d.low}
                  highLabel={d.high}
                  tooltip={d.tooltip}
                  value={dial[d.key]}
                  onChange={(v) => updateDial(d.key, v)}
                />
                {/* Impact indicator */}
                <div className="mt-1 flex items-center gap-4 pl-27 text-xs">
                  {impact.token_change_pct !== 0 && (
                    <span className={impact.token_change_pct < 0 ? "text-green-600" : "text-amber-600"}>
                      {impact.token_change_pct > 0 ? "+" : ""}{impact.token_change_pct.toFixed(0)}% tokens
                    </span>
                  )}
                  {impact.cost_change_pct !== 0 && (
                    <span className={impact.cost_change_pct < 0 ? "text-green-600" : "text-amber-600"}>
                      {impact.cost_change_pct > 0 ? "+" : ""}{impact.cost_change_pct.toFixed(0)}% custo
                    </span>
                  )}
                  {impact.quality_risk !== "none" && (
                    <span className={`flex items-center gap-1 ${riskColor(impact.quality_risk)}`}>
                      <AlertTriangle className="h-3 w-3" />
                      Risco {riskLabel(impact.quality_risk).toLowerCase()}
                    </span>
                  )}
                  <span className="text-[var(--color-text-muted)]">{impact.recommendation}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between">
        <div>
          {hasChanges && (
            <Badge variant="warning" dot>Alterações não salvas</Badge>
          )}
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleReset}
            className="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-text)]"
          >
            <RotateCcw className="h-4 w-4" />
            Restaurar padrão
          </button>
          <button
            onClick={() => setShowConfirm(true)}
            disabled={!hasChanges}
            className="flex cursor-pointer items-center gap-2 rounded-lg bg-[var(--color-cta)] px-4 py-2 text-sm font-semibold text-white transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            Salvar comportamento
          </button>
        </div>
      </div>

      {/* Confirm Modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-[var(--color-surface)] p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-[var(--color-text)]">Aplicar novo comportamento?</h3>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">
              A IA começará a se comportar de acordo com essas configurações imediatamente.
            </p>

            {/* Impact summary in modal */}
            <div className="mt-4 space-y-2 rounded-lg bg-white/5 p-4 text-sm">
              <div className="flex justify-between">
                <span className="text-[var(--color-text-muted)]">Impacto em tokens</span>
                <strong className={`font-[family-name:var(--font-mono)] ${totalTokenChange < 0 ? "text-green-600" : "text-amber-600"}`}>
                  {totalTokenChange > 0 ? "+" : ""}{totalTokenChange.toFixed(0)}%
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-text-muted)]">Impacto em custo</span>
                <strong className={`font-[family-name:var(--font-mono)] ${totalCostChange < 0 ? "text-green-600" : "text-amber-600"}`}>
                  {totalCostChange > 0 ? "+" : ""}{totalCostChange.toFixed(0)}%
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-text-muted)]">Nível de risco</span>
                <strong className={riskColor(maxRisk)}>{riskLabel(maxRisk)}</strong>
              </div>
            </div>

            {saveError && (
              <div className="mt-3 rounded-lg bg-red-950/50 px-3 py-2 text-xs text-red-400">
                {saveError}
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => { setShowConfirm(false); setSaveError(null); }} className="cursor-pointer rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)]">
                Cancelar
              </button>
              <button onClick={handleSave} disabled={saving} className="cursor-pointer rounded-lg bg-[var(--color-cta)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
                {saving ? "Salvando..." : "Aplicar agora"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
