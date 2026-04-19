"use client";

import { useState, useEffect } from "react";
import {
  Zap,
  Plus,
  AlertTriangle,
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  Shield,
  TrendingDown,
  DollarSign,
  Pencil,
  Check,
  X,
  Sparkles,
  ThumbsUp,
  ThumbsDown,
  Copy,
} from "lucide-react";
import { Toggle } from "@/components/ui/toggle";
import { Badge } from "@/components/ui/badge";
import { mockIntents, mockSecurityRules, mockModuleStats, mockSuggestions } from "@/lib/mock-data";
import {
  reloadIntents,
  reloadPolicies,
  setOverrides,
  getSuggestions,
  approveSuggestion,
  rejectSuggestion,
} from "@/lib/api";
import type { IntentSuggestion, SuggestionApprovalResponse } from "@/lib/types";

export function EstixePage() {
  const [bypassEnabled, setBypassEnabled] = useState(true);
  const [intents, setIntents] = useState(mockIntents);
  const [securityRules, setSecurityRules] = useState(mockSecurityRules);
  const [bypassConfidence, setBypassConfidence] = useState(85);
  const [blockConfidence, setBlockConfidence] = useState(70);
  const [showBypassWarning, setShowBypassWarning] = useState(false);
  const [thresholdSaved, setThresholdSaved] = useState(false);
  const [editingIntent, setEditingIntent] = useState<string | null>(null);
  const [editingResponse, setEditingResponse] = useState("");
  const [suggestions, setSuggestions] = useState<IntentSuggestion[]>([]);
  const [suggestionsLoaded, setSuggestionsLoaded] = useState(false);
  const [suggestionEditing, setSuggestionEditing] = useState<string | null>(null);
  const [suggestionName, setSuggestionName] = useState("");
  const [suggestionResp, setSuggestionResp] = useState("");
  const [approvalResult, setApprovalResult] = useState<SuggestionApprovalResponse | null>(null);
  const estixeStats = mockModuleStats.estixe;

  // Fetch suggestions from backend (fallback to mock if unreachable)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getSuggestions();
        if (!cancelled) {
          setSuggestions(res.suggestions ?? []);
          setSuggestionsLoaded(true);
        }
      } catch {
        if (!cancelled) {
          setSuggestions(mockSuggestions);
          setSuggestionsLoaded(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const startApproving = (s: IntentSuggestion) => {
    setSuggestionEditing(s.id);
    setSuggestionName(s.suggested_intent_name);
    setSuggestionResp("");
  };

  const cancelApproving = () => {
    setSuggestionEditing(null);
    setSuggestionName("");
    setSuggestionResp("");
  };

  const confirmApprove = async (s: IntentSuggestion) => {
    try {
      const res = await approveSuggestion(s.id, {
        intent_name: suggestionName,
        response: suggestionResp,
      });
      setApprovalResult(res);
      setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    } catch {
      // Fallback: local-only approval
      setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    } finally {
      cancelApproving();
    }
  };

  const handleReject = async (s: IntentSuggestion) => {
    try {
      await rejectSuggestion(s.id);
    } catch {}
    setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
  };

  const startEditing = (intentId: string, currentResponse: string) => {
    setEditingIntent(intentId);
    setEditingResponse(currentResponse);
  };

  const cancelEditing = () => {
    setEditingIntent(null);
    setEditingResponse("");
  };

  const saveIntentResponse = async (intentId: string) => {
    setIntents((prev) =>
      prev.map((i) => (i.id === intentId ? { ...i, response: editingResponse } : i))
    );
    // Persist via overrides API (user can reload intents file later to sync with YAML)
    try {
      await setOverrides({ [`intent_response_${intentId}`]: editingResponse });
    } catch {}
    setEditingIntent(null);
    setEditingResponse("");
  };

  const handleBypassToggle = (enabled: boolean) => {
    if (!enabled) {
      setShowBypassWarning(true);
    } else {
      setBypassEnabled(true);
    }
  };

  const confirmDisableBypass = () => {
    setBypassEnabled(false);
    setShowBypassWarning(false);
  };

  const toggleIntent = (id: string) => {
    setIntents((prev) =>
      prev.map((i) => (i.id === id ? { ...i, enabled: !i.enabled } : i))
    );
  };

  const toggleSecurity = (id: string) => {
    setSecurityRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r))
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          <span className="text-teal-600">ESTIXE</span> — Proteção
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          Controle e proteção em tempo real. Cada bloqueio e desvio economiza custo e reduz risco.
        </p>
      </div>

      {/* ═══ HERO — Impacto do ESTIXE ═══ */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-teal-800/50 bg-gradient-to-br from-teal-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-teal-600">
            <Zap className="h-3.5 w-3.5" />
            Desvios hoje
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-teal-200">
            {estixeStats.bypasses_today.toLocaleString("pt-BR")}
          </div>
          <div className="mt-0.5 text-xs text-teal-600">chamadas à IA evitadas</div>
        </div>
        <div className="rounded-xl border border-teal-800/50 bg-gradient-to-br from-teal-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-green-600">
            <DollarSign className="h-3.5 w-3.5" />
            Custo evitado
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-green-400">
            R$ {estixeStats.cost_avoided.toFixed(2)}
          </div>
          <div className="mt-0.5 text-xs text-green-600">economia por desvio e bloqueio</div>
        </div>
        <div className="rounded-xl border border-red-800/50 bg-gradient-to-br from-red-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-red-600">
            <ShieldAlert className="h-3.5 w-3.5" />
            Ameaças detectadas
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-red-400">
            {estixeStats.threats_detected}
          </div>
          <div className="mt-0.5 text-xs text-red-600">injeções e vazamentos bloqueados</div>
        </div>
        <div className="rounded-xl border border-teal-800/50 bg-gradient-to-br from-teal-950/50 to-transparent p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-teal-600">
            <TrendingDown className="h-3.5 w-3.5" />
            Tokens poupados
          </div>
          <div className="mt-2 font-[family-name:var(--font-mono)] text-2xl font-bold text-teal-200">
            {(estixeStats.tokens_saved / 1000).toFixed(0)}k
          </div>
          <div className="mt-0.5 text-xs text-teal-600">por desvios inteligentes</div>
        </div>
      </div>

      {/* Bypass Toggle + Impact */}
      <div className={`rounded-xl border p-6 ${
        bypassEnabled
          ? "border-[var(--color-primary)]/30 bg-[var(--color-primary)]/5"
          : "border-red-200 bg-red-950/50"
      }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className={`h-5 w-5 ${bypassEnabled ? "text-[var(--color-primary)]" : "text-red-500"}`} />
            <div>
              <h2 className="text-sm font-semibold text-[var(--color-text)]">Desvio inteligente</h2>
              <p className="text-xs text-[var(--color-text-muted)]">
                {bypassEnabled
                  ? `Ativo — economizando ~R$ ${(estixeStats.cost_avoided / 24 * new Date().getHours()).toFixed(2)}/hora`
                  : "Desativado — todas as mensagens vão para a IA"}
              </p>
            </div>
          </div>
          <Toggle enabled={bypassEnabled} onChange={handleBypassToggle} label="Desvio ativado" />
        </div>
      </div>

      {/* Bypass Categories */}
      {bypassEnabled && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Categorias de desvio</h2>
            <button
              onClick={async () => { try { await reloadIntents(); } catch {} }}
              className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-text)]"
            >
              <Plus className="h-3.5 w-3.5" />
              Recarregar intents
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {intents.map((intent) => (
              <div
                key={intent.id}
                className={`rounded-xl border p-4 transition-colors ${
                  intent.enabled
                    ? "border-[var(--color-border)] bg-[var(--color-surface)]"
                    : "border-slate-700 bg-white/5 opacity-60"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-[var(--color-text)]">{intent.name}</span>
                  <Toggle enabled={intent.enabled} onChange={() => toggleIntent(intent.id)} label={intent.name} />
                </div>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  {intent.examples.slice(0, 4).join(", ")}
                  {intent.examples.length > 4 && ` +${intent.examples.length - 4}`}
                </p>

                {editingIntent === intent.id ? (
                  <div className="mt-2 space-y-2">
                    <textarea
                      value={editingResponse}
                      onChange={(e) => setEditingResponse(e.target.value)}
                      rows={2}
                      className="w-full resize-none rounded-lg border border-[var(--color-primary)]/50 bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text)] outline-none focus:border-[var(--color-primary)]"
                      placeholder="Resposta automatica para essa categoria..."
                    />
                    <div className="flex justify-end gap-1.5">
                      <button
                        onClick={cancelEditing}
                        className="flex cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                      >
                        <X className="h-3 w-3" />
                        Cancelar
                      </button>
                      <button
                        onClick={() => saveIntentResponse(intent.id)}
                        disabled={!editingResponse.trim() || editingResponse === intent.response}
                        className="flex cursor-pointer items-center gap-1 rounded bg-[var(--color-cta)] px-2 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Check className="h-3 w-3" />
                        Salvar
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="group mt-2 flex items-start gap-2 rounded-lg bg-white/5 px-3 py-2 text-xs text-[var(--color-text-muted)]">
                    <div className="flex-1">
                      <span className="font-medium">Resposta:</span> {intent.response}
                    </div>
                    <button
                      onClick={() => startEditing(intent.id, intent.response)}
                      className="opacity-0 cursor-pointer text-[var(--color-text-muted)] transition-opacity group-hover:opacity-100 hover:text-[var(--color-primary)]"
                      aria-label="Editar resposta"
                      title="Editar resposta"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Suggestions — auto-discovery */}
      {suggestionsLoaded && suggestions.length > 0 && (
        <div className="rounded-xl border border-amber-800/50 bg-gradient-to-br from-amber-950/30 to-transparent p-5">
          <div className="mb-4 flex items-start justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-900/30">
                <Sparkles className="h-4 w-4 text-amber-400" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-[var(--color-text)]">
                  Novas categorias sugeridas
                </h2>
                <p className="text-xs text-[var(--color-text-muted)]">
                  O AION detectou clusters de perguntas repetidas que poderiam virar bypass. Aprove para economizar.
                </p>
              </div>
            </div>
            <Badge variant="warning">{suggestions.length} sugestões</Badge>
          </div>

          <div className="space-y-3">
            {suggestions.map((s) => (
              <div key={s.id} className="rounded-lg border border-amber-900/50 bg-[var(--color-surface)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <code className="font-[family-name:var(--font-mono)] text-sm font-semibold text-amber-400">
                        {s.suggested_intent_name}
                      </code>
                      <Badge variant="muted">{s.cluster_size} requests</Badge>
                      <Badge variant="success">
                        ~R$ {s.estimated_daily_savings.toFixed(2)}/dia
                      </Badge>
                      <span className="text-[10px] text-[var(--color-text-muted)]">
                        confiança: {(s.confidence * 100).toFixed(0)}%
                      </span>
                    </div>

                    <div className="mt-2 space-y-1">
                      {s.sample_messages.slice(0, 3).map((msg, i) => (
                        <div
                          key={i}
                          className="truncate rounded bg-white/5 px-2 py-1 text-xs text-[var(--color-text-muted)]"
                        >
                          &quot;{msg}&quot;
                        </div>
                      ))}
                      {s.sample_messages.length > 3 && (
                        <div className="text-[10px] text-[var(--color-text-muted)]">
                          +{s.sample_messages.length - 3} exemplos similares
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-col gap-1.5">
                    <button
                      onClick={() => startApproving(s)}
                      className="flex cursor-pointer items-center gap-1 rounded bg-green-900/40 px-2 py-1 text-xs font-semibold text-green-300 hover:bg-green-900/60"
                      title="Aprovar"
                    >
                      <ThumbsUp className="h-3 w-3" />
                      Aprovar
                    </button>
                    <button
                      onClick={() => handleReject(s)}
                      className="flex cursor-pointer items-center gap-1 rounded bg-red-900/30 px-2 py-1 text-xs font-semibold text-red-300 hover:bg-red-900/50"
                      title="Rejeitar — não mostrar de novo"
                    >
                      <ThumbsDown className="h-3 w-3" />
                      Rejeitar
                    </button>
                  </div>
                </div>

                {/* Approval editor (inline) */}
                {suggestionEditing === s.id && (
                  <div className="mt-3 space-y-2 rounded border border-[var(--color-primary)]/50 bg-[var(--color-bg)] p-3">
                    <div>
                      <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                        Nome do intent
                      </label>
                      <input
                        type="text"
                        value={suggestionName}
                        onChange={(e) => setSuggestionName(e.target.value)}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text)] outline-none focus:border-[var(--color-primary)]"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                        Resposta automática
                      </label>
                      <textarea
                        value={suggestionResp}
                        onChange={(e) => setSuggestionResp(e.target.value)}
                        rows={2}
                        placeholder="Digite a resposta que o AION enviará para esse intent..."
                        className="w-full resize-none rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-xs text-[var(--color-text)] outline-none focus:border-[var(--color-primary)]"
                      />
                    </div>
                    <div className="flex justify-end gap-1.5">
                      <button
                        onClick={cancelApproving}
                        className="flex cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                      >
                        <X className="h-3 w-3" /> Cancelar
                      </button>
                      <button
                        onClick={() => confirmApprove(s)}
                        disabled={!suggestionName.trim() || !suggestionResp.trim()}
                        className="flex cursor-pointer items-center gap-1 rounded bg-[var(--color-cta)] px-2 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Check className="h-3 w-3" /> Criar intent
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Approval result modal */}
      {approvalResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl bg-[var(--color-surface)] p-6 shadow-xl">
            <div className="mb-4 flex items-center gap-2">
              <Check className="h-5 w-5 text-green-400" />
              <h3 className="text-lg font-semibold text-[var(--color-text)]">
                Intent &quot;{approvalResult.intent_name}&quot; aprovado
              </h3>
            </div>
            <p className="text-xs text-[var(--color-text-muted)]">
              {approvalResult.note}
            </p>
            <div className="mt-3 relative">
              <pre className="overflow-x-auto rounded-lg bg-[var(--color-bg)] p-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text)]">
                {approvalResult.yaml_snippet}
              </pre>
              <button
                onClick={() => navigator.clipboard.writeText(approvalResult.yaml_snippet)}
                className="absolute right-2 top-2 cursor-pointer rounded bg-[var(--color-surface)] p-1 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                title="Copiar"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => setApprovalResult(null)}
                className="cursor-pointer rounded-lg bg-[var(--color-cta)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                Entendi
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Security Rules */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-6 py-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <Shield className="h-4 w-4 text-[var(--color-primary)]" />
            Guardrails ativos
          </h2>
          <p className="text-xs text-[var(--color-text-muted)]">
            {securityRules.filter((r) => r.enabled).length}/{securityRules.length} proteções habilitadas
          </p>
        </div>
        <div className="divide-y divide-[var(--color-border)]">
          {securityRules.map((rule) => (
            <div key={rule.id} className="flex items-center justify-between px-6 py-4">
              <div className="flex items-center gap-3">
                {rule.enabled ? (
                  rule.severity === "critical" ? (
                    <ShieldAlert className="h-5 w-5 text-red-500" />
                  ) : (
                    <ShieldCheck className="h-5 w-5 text-[var(--color-primary)]" />
                  )
                ) : (
                  <ShieldOff className="h-5 w-5 text-[var(--color-text-muted)]" />
                )}
                <div>
                  <div className="text-sm font-medium text-[var(--color-text)]">{rule.name}</div>
                  <div className="text-xs text-[var(--color-text-muted)]">{rule.description}</div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Badge variant={
                  rule.severity === "critical" ? "error"
                    : rule.severity === "high" ? "warning"
                    : "muted"
                }>
                  {rule.severity}
                </Badge>
                <Toggle enabled={rule.enabled} onChange={() => toggleSecurity(rule.id)} label={rule.name} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Thresholds */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="mb-1 text-sm font-semibold text-[var(--color-text)]">Limites de decisão</h2>
            <p className="text-xs text-[var(--color-text-muted)]">
              Definem quando o ESTIXE age. Valores mais altos = menos falsos positivos, mais chamadas à IA.
            </p>
          </div>
          <button
            onClick={async () => {
              try {
                await setOverrides({ bypass_threshold: bypassConfidence / 100 });
                setThresholdSaved(true);
                setTimeout(() => setThresholdSaved(false), 2000);
              } catch {}
            }}
            className="flex cursor-pointer items-center gap-1.5 rounded-lg bg-[var(--color-cta)] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:opacity-90"
          >
            {thresholdSaved ? "Salvo!" : "Salvar limites"}
          </button>
        </div>

        <div className="mt-4 space-y-6">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-[var(--color-text)]">Confiança para desvio</span>
              <span className="font-[family-name:var(--font-mono)] text-sm font-bold text-[var(--color-primary)]">
                {bypassConfidence}%
              </span>
            </div>
            <input
              type="range"
              min={50}
              max={99}
              value={bypassConfidence}
              onChange={(e) => setBypassConfidence(Number(e.target.value))}
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-white/15 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-primary)] [&::-webkit-slider-thumb]:shadow-md"
              aria-label="Confiança para desvio"
            />
            {bypassConfidence < 70 && (
              <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-600">
                <AlertTriangle className="h-3.5 w-3.5" />
                Limite baixo — pode desviar perguntas que deveriam ir para a IA.
              </div>
            )}
            {bypassConfidence > 90 && (
              <div className="mt-2 text-xs text-[var(--color-text-muted)]">
                Limite alto — menos desvios, mais chamadas à IA, mais custo.
              </div>
            )}
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-[var(--color-text)]">Confiança para bloqueio</span>
              <span className="font-[family-name:var(--font-mono)] text-sm font-bold text-[var(--color-primary)]">
                {blockConfidence}%
              </span>
            </div>
            <input
              type="range"
              min={50}
              max={99}
              value={blockConfidence}
              onChange={(e) => setBlockConfidence(Number(e.target.value))}
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-white/15 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-primary)] [&::-webkit-slider-thumb]:shadow-md"
              aria-label="Confiança para bloqueio"
            />
          </div>
        </div>
      </div>

      {/* Bypass Warning Modal */}
      {showBypassWarning && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-[var(--color-surface)] p-8 shadow-xl">
            <div className="mb-4 flex items-center gap-3">
              <AlertTriangle className="h-6 w-6 text-amber-500" />
              <h3 className="text-lg font-semibold text-[var(--color-text)]">Desativar desvio?</h3>
            </div>
            <p className="text-sm text-[var(--color-text-muted)]">
              Todas as mensagens serão enviadas para a IA. Estimativa de impacto:
            </p>
            <div className="mt-3 space-y-2 rounded-lg bg-amber-950/50 p-4 text-sm">
              <div className="flex justify-between">
                <span className="text-amber-400">Custo adicional estimado</span>
                <strong className="font-[family-name:var(--font-mono)] text-amber-200">+R$ {estixeStats.cost_avoided.toFixed(2)}/dia</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-amber-400">Chamadas extras à IA</span>
                <strong className="font-[family-name:var(--font-mono)] text-amber-200">+{estixeStats.bypasses_today.toLocaleString("pt-BR")}/dia</strong>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowBypassWarning(false)} className="cursor-pointer rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)]">
                Cancelar
              </button>
              <button onClick={confirmDisableBypass} className="cursor-pointer rounded-lg bg-amber-950/500 px-4 py-2 text-sm font-semibold text-white">
                Desativar mesmo assim
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
