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
import { mockIntents, mockBlockCategories, mockBlockSuggestions, mockSecurityRules, mockModuleStats, mockSuggestions, mockThreatCategories } from "@/lib/mock-data";
import type { BlockCategory } from "@/lib/types";
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
  const [initialBypassConfidence] = useState(85);
  const [initialBlockConfidence] = useState(70);
  const [showBypassWarning, setShowBypassWarning] = useState(false);
  const [showConfirmThreshold, setShowConfirmThreshold] = useState(false);
  const [thresholdSaved, setThresholdSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const hasThresholdChanges = bypassConfidence !== initialBypassConfidence || blockConfidence !== initialBlockConfidence;
  const bypassImpact = (initialBypassConfidence - bypassConfidence) * 0.02; // Cada % altera ~2% no custo
  const blockImpact = (initialBlockConfidence - blockConfidence) * 0.015;
  const [editingIntent, setEditingIntent] = useState<string | null>(null);
  const [editingResponse, setEditingResponse] = useState("");
  const [suggestions, setSuggestions] = useState<IntentSuggestion[]>([]);
  const [suggestionsLoaded, setSuggestionsLoaded] = useState(false);
  const [suggestionEditing, setSuggestionEditing] = useState<string | null>(null);
  const [suggestionName, setSuggestionName] = useState("");
  const [suggestionResp, setSuggestionResp] = useState("");
  const [approvalResult, setApprovalResult] = useState<SuggestionApprovalResponse | null>(null);
  const [pendingReload, setPendingReload] = useState<Array<{
    id: string;
    name: string;
    examples: string[];
    response: string;
  }>>([]);
  const [reloading, setReloading] = useState(false);

  // Block categories state
  const [blockCategories, setBlockCategories] = useState<(BlockCategory & { isNew?: boolean })[]>(mockBlockCategories);
  const [editingBlock, setEditingBlock] = useState<string | null>(null);
  const [editingBlockResponse, setEditingBlockResponse] = useState("");
  const [blockSuggestions, setBlockSuggestions] = useState(mockBlockSuggestions);
  const [blockSuggestionEditing, setBlockSuggestionEditing] = useState<string | null>(null);
  const [blockSuggestionName, setBlockSuggestionName] = useState("");
  const [blockSuggestionResp, setBlockSuggestionResp] = useState("");
  const [pendingBlockReload, setPendingBlockReload] = useState<Array<{
    id: string;
    name: string;
    severity: "critical" | "high" | "medium";
    examples: string[];
    response: string;
  }>>([]);
  const [reloadingBlock, setReloadingBlock] = useState(false);
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
    } catch {
      // Fallback: local-only approval
    }
    // Move to pending reload — will appear in bypass categories after user clicks "Recarregar"
    setPendingReload((prev) => [
      ...prev,
      {
        id: `pending_${s.id}`,
        name: suggestionName,
        examples: s.sample_messages,
        response: suggestionResp,
      },
    ]);
    setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    cancelApproving();
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

  // Block category handlers
  const toggleBlock = (id: string) => {
    setBlockCategories((prev) =>
      prev.map((b) => (b.id === id ? { ...b, enabled: !b.enabled } : b))
    );
  };

  const startEditingBlock = (id: string, current: string) => {
    setEditingBlock(id);
    setEditingBlockResponse(current);
  };

  const cancelEditingBlock = () => {
    setEditingBlock(null);
    setEditingBlockResponse("");
  };

  const saveBlockResponse = (id: string) => {
    setBlockCategories((prev) =>
      prev.map((b) => b.id === id ? { ...b, response: editingBlockResponse, isNew: false } : b)
    );
    cancelEditingBlock();
  };

  const startApprovingBlock = (s: typeof blockSuggestions[number]) => {
    setBlockSuggestionEditing(s.id);
    setBlockSuggestionName(s.suggested_intent_name);
    setBlockSuggestionResp(s.suggested_response ?? "");
  };

  const cancelApprovingBlock = () => {
    setBlockSuggestionEditing(null);
    setBlockSuggestionName("");
    setBlockSuggestionResp("");
  };

  const confirmApproveBlock = (s: typeof blockSuggestions[number]) => {
    setPendingBlockReload((prev) => [
      ...prev,
      {
        id: `blk_pending_${s.id}`,
        name: blockSuggestionName,
        severity: "high" as const,
        examples: s.sample_messages,
        response: blockSuggestionResp,
      },
    ]);
    setBlockSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    cancelApprovingBlock();
  };

  const rejectBlockSuggestion = (id: string) => {
    setBlockSuggestions((prev) => prev.filter((s) => s.id !== id));
  };

  const toggleSecurity = (id: string) => {
    setSecurityRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r))
    );
  };

  const handleSaveThreshold = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await setOverrides({
        bypass_threshold: bypassConfidence / 100,
        block_threshold: blockConfidence / 100,
      });
      setThresholdSaved(true);
      setTimeout(() => setThresholdSaved(false), 2000);
      setShowConfirmThreshold(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const handleCancelThreshold = () => {
    setShowConfirmThreshold(false);
    setSaveError(null);
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

      {/* ═══ MASTER CONTROL — Bypass ═══ */}
      <div className={`rounded-2xl border-2 p-6 transition-all duration-300 ${
        bypassEnabled
          ? "border-teal-600/50 bg-gradient-to-r from-teal-950/60 to-teal-900/20"
          : "border-red-600/60 bg-gradient-to-r from-red-950/70 to-red-900/30"
      }`}>
        <div className="flex items-center justify-between gap-6">
          {/* Left — status */}
          <div className="flex items-center gap-5">
            <div className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl ${
              bypassEnabled ? "bg-teal-900/60" : "bg-red-900/60"
            }`}>
              <Zap className={`h-7 w-7 ${bypassEnabled ? "text-teal-300" : "text-red-400"}`} />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h2 className="text-base font-bold text-[var(--color-text)]">Desvio inteligente</h2>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider ${
                  bypassEnabled
                    ? "bg-teal-500/20 text-teal-300"
                    : "bg-red-500/20 text-red-400"
                }`}>
                  {bypassEnabled ? "● Ativo" : "○ Desligado"}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                {bypassEnabled
                  ? "Mensagens de baixo risco são respondidas sem chamar a IA"
                  : "Bypass desativado — 100% das mensagens estão sendo enviadas para a IA"}
              </p>
            </div>
          </div>

          {/* Center — live metrics (only when active) */}
          {bypassEnabled ? (
            <div className="hidden flex-1 items-center justify-center gap-8 lg:flex">
              <div className="text-center">
                <p className="font-[family-name:var(--font-mono)] text-2xl font-bold text-teal-200">
                  R$ {(estixeStats.cost_avoided / 24 * new Date().getHours()).toFixed(2)}
                </p>
                <p className="text-xs text-teal-600">economizado hoje</p>
              </div>
              <div className="h-8 w-px bg-teal-800/50" />
              <div className="text-center">
                <p className="font-[family-name:var(--font-mono)] text-2xl font-bold text-teal-200">
                  {estixeStats.bypasses_today.toLocaleString("pt-BR")}
                </p>
                <p className="text-xs text-teal-600">chamadas desviadas hoje</p>
              </div>
              <div className="h-8 w-px bg-teal-800/50" />
              <div className="text-center">
                <p className="font-[family-name:var(--font-mono)] text-2xl font-bold text-teal-200">
                  {(estixeStats.tokens_saved / 1000).toFixed(0)}k
                </p>
                <p className="text-xs text-teal-600">tokens poupados</p>
              </div>
            </div>
          ) : (
            <div className="hidden flex-1 items-center justify-center lg:flex">
              <div className="flex items-center gap-3 rounded-xl border border-red-700/50 bg-red-900/20 px-5 py-3">
                <AlertTriangle className="h-5 w-5 shrink-0 text-red-400" />
                <div>
                  <p className="text-sm font-semibold text-red-300">Impacto ativo</p>
                  <p className="text-xs text-red-400">
                    +R$ {estixeStats.cost_avoided.toFixed(2)}/dia em custo adicional estimado
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Right — toggle */}
          <div className="flex shrink-0 flex-col items-center gap-2">
            <Toggle enabled={bypassEnabled} onChange={handleBypassToggle} label="Desvio ativado" />
            <span className={`text-[10px] font-medium uppercase tracking-wider ${
              bypassEnabled ? "text-teal-600" : "text-red-500"
            }`}>
              {bypassEnabled ? "Desligar" : "Religar"}
            </span>
          </div>
        </div>
      </div>

      {/* ═══ THREAT CATEGORIES ═══ */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="border-b border-[var(--color-border)] px-6 py-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <ShieldAlert className="h-4 w-4 text-red-400" />
            Categorias de ameaça detectadas
          </h2>
          <p className="text-xs text-[var(--color-text-muted)]">
            {mockThreatCategories.reduce((s, t) => s + t.count, 0).toLocaleString("pt-BR")} bloqueios este mês
          </p>
        </div>
        <div className="divide-y divide-[var(--color-border)]/50">
          {mockThreatCategories.map((threat) => (
            <div key={threat.name} className="flex items-center gap-4 px-6 py-3">
              <div className="w-44 shrink-0 text-sm text-[var(--color-text)]">{threat.name}</div>
              <div className="flex-1">
                <div className="h-1.5 w-full rounded-full bg-white/10">
                  <div
                    className={`h-1.5 rounded-full ${
                      threat.action === "block"
                        ? "bg-red-500"
                        : threat.action === "sanitize"
                        ? "bg-amber-500"
                        : "bg-yellow-400"
                    }`}
                    style={{ width: `${threat.pct}%` }}
                  />
                </div>
              </div>
              <span className="w-10 text-right font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                {threat.count}
              </span>
              <span className="w-12 text-right text-xs text-[var(--color-text-muted)]">
                {threat.pct.toFixed(1)}%
              </span>
              <Badge
                variant={
                  threat.action === "block"
                    ? "error"
                    : threat.action === "sanitize"
                    ? "warning"
                    : "muted"
                }
              >
                {threat.action}
              </Badge>
            </div>
          ))}
        </div>
      </div>

      {/* Bypass Categories */}
      {bypassEnabled && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Categorias de desvio</h2>
            <button
              onClick={async () => {
                if (pendingReload.length === 0) return;
                setReloading(true);
                try { await reloadIntents(); } catch {}
                // Add approved intents as disabled — user must review and activate
                setIntents((prev) => [
                  ...prev,
                  ...pendingReload.map((p) => ({
                    id: p.id,
                    name: p.name,
                    enabled: false,
                    examples: p.examples,
                    response: p.response,
                    isNew: true,
                  })),
                ]);
                setPendingReload([]);
                setReloading(false);
              }}
              disabled={reloading}
              className={`relative flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-wait disabled:opacity-60 ${
                pendingReload.length > 0
                  ? "border-amber-700/60 bg-amber-900/20 text-amber-300 hover:bg-amber-900/30"
                  : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-primary)] hover:text-[var(--color-text)]"
              }`}
            >
              <Plus className="h-3.5 w-3.5" />
              {reloading ? "Recarregando..." : "Recarregar intents"}
              {pendingReload.length > 0 && (
                <span className="ml-1 flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-black">
                  {pendingReload.length}
                </span>
              )}
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {intents.map((intent) => {
              const isNew = (intent as typeof intent & { isNew?: boolean }).isNew === true;
              return (
              <div
                key={intent.id}
                className={`rounded-xl border p-4 transition-colors ${
                  isNew
                    ? "border-amber-700/50 bg-amber-950/20"
                    : intent.enabled
                    ? "border-[var(--color-border)] bg-[var(--color-surface)]"
                    : "border-slate-700 bg-white/5 opacity-60"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-[var(--color-text)]">{intent.name}</span>
                    {isNew && (
                      <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-400">
                        Novo
                      </span>
                    )}
                  </div>
                  <Toggle
                    enabled={intent.enabled}
                    onChange={() => toggleIntent(intent.id)}
                    label={intent.name}
                    disabled={isNew}
                  />
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
                        onClick={async () => {
                          await saveIntentResponse(intent.id);
                          // After saving response, remove isNew flag so toggle becomes active
                          if (isNew) {
                            setIntents((prev) =>
                              prev.map((i) =>
                                i.id === intent.id
                                  ? { ...i, isNew: false } as typeof i
                                  : i
                              )
                            );
                          }
                        }}
                        disabled={!editingResponse.trim() || editingResponse === intent.response}
                        className="flex cursor-pointer items-center gap-1 rounded bg-[var(--color-cta)] px-2 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Check className="h-3 w-3" />
                        Salvar
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className={`group mt-2 flex items-start gap-2 rounded-lg px-3 py-2 text-xs text-[var(--color-text-muted)] ${
                    isNew ? "border border-amber-700/40 bg-amber-900/10" : "bg-white/5"
                  }`}>
                    <div className="flex-1">
                      <span className="font-medium">Resposta:</span> {intent.response}
                    </div>
                    <button
                      onClick={() => startEditing(intent.id, intent.response)}
                      className="cursor-pointer text-[var(--color-text-muted)] transition-opacity opacity-0 group-hover:opacity-100 hover:text-[var(--color-primary)]"
                      aria-label="Editar resposta"
                      title="Editar resposta"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}

                {/* New intent — prompt to review before activating */}
                {isNew && !editingIntent && (
                  <div className="mt-2 flex items-center justify-between rounded-lg bg-amber-900/20 px-3 py-2">
                    <p className="text-xs text-amber-400">Revise a resposta e ative quando pronto</p>
                    <button
                      onClick={() => {
                        setIntents((prev) =>
                          prev.map((i) =>
                            i.id === intent.id ? { ...i, isNew: false, enabled: true } as typeof i : i
                          )
                        );
                      }}
                      className="ml-3 shrink-0 cursor-pointer rounded bg-amber-600 px-2 py-0.5 text-xs font-semibold text-white hover:opacity-90"
                    >
                      Ativar
                    </button>
                  </div>
                )}
              </div>
              );
            })}
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

      {/* ═══ BLOCK CATEGORIES ═══ */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Categorias de bloqueio</h2>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              Padrões bloqueados antes de chegar à IA. Configure a mensagem exibida ao usuário.
            </p>
          </div>
          <button
            onClick={async () => {
              if (pendingBlockReload.length === 0) return;
              setReloadingBlock(true);
              try { await reloadPolicies(); } catch {}
              setBlockCategories((prev) => [
                ...prev,
                ...pendingBlockReload.map((p) => ({
                  ...p,
                  enabled: false,
                  isNew: true,
                })),
              ]);
              setPendingBlockReload([]);
              setReloadingBlock(false);
            }}
            disabled={reloadingBlock}
            className={`relative flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-wait disabled:opacity-60 ${
              pendingBlockReload.length > 0
                ? "border-amber-700/60 bg-amber-900/20 text-amber-300 hover:bg-amber-900/30"
                : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-primary)] hover:text-[var(--color-text)]"
            }`}
          >
            <Plus className="h-3.5 w-3.5" />
            {reloadingBlock ? "Recarregando..." : "Recarregar bloqueios"}
            {pendingBlockReload.length > 0 && (
              <span className="ml-1 flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-bold text-black">
                {pendingBlockReload.length}
              </span>
            )}
          </button>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {blockCategories.map((block) => {
            const severityStyle = {
              critical: { dot: "bg-red-500", label: "Crítico", ring: "border-red-800/40" },
              high: { dot: "bg-amber-500", label: "Alto", ring: "border-amber-800/30" },
              medium: { dot: "bg-yellow-500", label: "Médio", ring: "border-yellow-800/20" },
            }[block.severity];

            return (
              <div
                key={block.id}
                className={`rounded-xl border p-4 transition-colors ${
                  block.isNew
                    ? "border-amber-700/50 bg-amber-950/20"
                    : block.enabled
                    ? `${severityStyle.ring} bg-[var(--color-surface)]`
                    : "border-slate-700 bg-white/5 opacity-60"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${severityStyle.dot}`} />
                    <span className="text-sm font-semibold text-[var(--color-text)]">{block.name}</span>
                    <span className="text-[10px] text-[var(--color-text-muted)]">{severityStyle.label}</span>
                    {block.isNew && (
                      <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-400">
                        Novo
                      </span>
                    )}
                  </div>
                  <Toggle
                    enabled={block.enabled}
                    onChange={() => toggleBlock(block.id)}
                    label={block.name}
                    disabled={block.isNew}
                  />
                </div>

                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  {block.examples.slice(0, 3).join(", ")}
                  {block.examples.length > 3 && ` +${block.examples.length - 3}`}
                </p>

                {editingBlock === block.id ? (
                  <div className="mt-2 space-y-2">
                    <textarea
                      value={editingBlockResponse}
                      onChange={(e) => setEditingBlockResponse(e.target.value)}
                      rows={2}
                      className="w-full resize-none rounded-lg border border-red-800/50 bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-text)] outline-none focus:border-red-600"
                      placeholder="Mensagem exibida ao usuário quando bloqueado..."
                    />
                    <div className="flex justify-end gap-1.5">
                      <button
                        onClick={cancelEditingBlock}
                        className="flex cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                      >
                        <X className="h-3 w-3" />
                        Cancelar
                      </button>
                      <button
                        onClick={() => saveBlockResponse(block.id)}
                        disabled={!editingBlockResponse.trim() || editingBlockResponse === block.response}
                        className="flex cursor-pointer items-center gap-1 rounded bg-red-700 px-2 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Check className="h-3 w-3" />
                        Salvar
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className={`group mt-2 flex items-start gap-2 rounded-lg px-3 py-2 text-xs text-[var(--color-text-muted)] ${
                    block.isNew ? "border border-amber-700/40 bg-amber-900/10" : "bg-white/5"
                  }`}>
                    <div className="flex-1">
                      <span className="font-medium">Resposta ao usuário:</span> {block.response}
                    </div>
                    <button
                      onClick={() => startEditingBlock(block.id, block.response)}
                      className="cursor-pointer opacity-0 text-[var(--color-text-muted)] transition-opacity group-hover:opacity-100 hover:text-red-400"
                      title="Editar mensagem"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}

                {block.isNew && !editingBlock && (
                  <div className="mt-2 flex items-center justify-between rounded-lg bg-amber-900/20 px-3 py-2">
                    <p className="text-xs text-amber-400">Revise a resposta e ative quando pronto</p>
                    <button
                      onClick={() =>
                        setBlockCategories((prev) =>
                          prev.map((b) =>
                            b.id === block.id ? { ...b, isNew: false, enabled: true } : b
                          )
                        )
                      }
                      className="ml-3 shrink-0 cursor-pointer rounded bg-red-700 px-2 py-0.5 text-xs font-semibold text-white hover:opacity-90"
                    >
                      Ativar
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Block Suggestions — NEMOS auto-discovery */}
      {blockSuggestions.length > 0 && (
        <div className="rounded-xl border border-red-800/40 bg-gradient-to-br from-red-950/20 to-transparent p-5">
          <div className="mb-4 flex items-start justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-900/40">
                <ShieldAlert className="h-4 w-4 text-red-400" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-[var(--color-text)]">
                  Novos padrões de ataque detectados
                </h2>
                <p className="text-xs text-[var(--color-text-muted)]">
                  O AION identificou clusters de tentativas bloqueadas que podem virar categorias permanentes.
                </p>
              </div>
            </div>
            <Badge variant="error">{blockSuggestions.length} sugestões</Badge>
          </div>

          <div className="space-y-3">
            {blockSuggestions.map((s) => (
              <div key={s.id} className="rounded-lg border border-red-900/50 bg-[var(--color-surface)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <code className="font-[family-name:var(--font-mono)] text-sm font-semibold text-red-400">
                        {s.suggested_intent_name}
                      </code>
                      <Badge variant="muted">{s.cluster_size} tentativas</Badge>
                      <span className="text-[10px] text-[var(--color-text-muted)]">
                        confiança: {(s.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="mt-2 space-y-1">
                      {s.sample_messages.slice(0, 3).map((msg, i) => (
                        <div key={i} className="truncate rounded bg-white/5 px-2 py-1 text-xs text-[var(--color-text-muted)]">
                          &quot;{msg}&quot;
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-col gap-1.5">
                    <button
                      onClick={() => startApprovingBlock(s)}
                      className="flex cursor-pointer items-center gap-1 rounded bg-red-900/40 px-2 py-1 text-xs font-semibold text-red-300 hover:bg-red-900/60"
                    >
                      <ThumbsUp className="h-3 w-3" />
                      Aprovar
                    </button>
                    <button
                      onClick={() => rejectBlockSuggestion(s.id)}
                      className="flex cursor-pointer items-center gap-1 rounded bg-white/5 px-2 py-1 text-xs font-semibold text-[var(--color-text-muted)] hover:bg-white/10"
                    >
                      <ThumbsDown className="h-3 w-3" />
                      Rejeitar
                    </button>
                  </div>
                </div>

                {blockSuggestionEditing === s.id && (
                  <div className="mt-3 space-y-2 rounded border border-red-700/50 bg-[var(--color-bg)] p-3">
                    <div>
                      <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                        Nome da categoria
                      </label>
                      <input
                        type="text"
                        value={blockSuggestionName}
                        onChange={(e) => setBlockSuggestionName(e.target.value)}
                        className="w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text)] outline-none focus:border-red-600"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                        Mensagem ao usuário quando bloqueado
                      </label>
                      <textarea
                        value={blockSuggestionResp}
                        onChange={(e) => setBlockSuggestionResp(e.target.value)}
                        rows={2}
                        placeholder="Ex: Essa solicitação não pode ser atendida..."
                        className="w-full resize-none rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-xs text-[var(--color-text)] outline-none focus:border-red-600"
                      />
                    </div>
                    <div className="flex justify-end gap-1.5">
                      <button
                        onClick={cancelApprovingBlock}
                        className="flex cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                      >
                        <X className="h-3 w-3" /> Cancelar
                      </button>
                      <button
                        onClick={() => confirmApproveBlock(s)}
                        disabled={!blockSuggestionName.trim() || !blockSuggestionResp.trim()}
                        className="flex cursor-pointer items-center gap-1 rounded bg-red-700 px-2 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Check className="h-3 w-3" /> Criar categoria
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
          <div className="flex items-start justify-between">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
                <Shield className="h-4 w-4 text-[var(--color-primary)]" />
                Proteções ativas
              </h2>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                {securityRules.filter((r) => r.enabled).length}/{securityRules.length} habilitadas
              </p>
            </div>
            <div className="flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
                Bloqueia a mensagem
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                Alerta a equipe
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full bg-slate-400" />
                Só registra
              </span>
            </div>
          </div>
        </div>
        <div className="divide-y divide-[var(--color-border)]">
          {securityRules.map((rule) => {
            const consequence =
              rule.severity === "critical"
                ? { label: "Bloqueia", color: "bg-red-500/10 text-red-400 ring-1 ring-red-500/30", dot: "bg-red-500" }
                : rule.severity === "high"
                ? { label: "Alerta", color: "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/30", dot: "bg-amber-400" }
                : { label: "Registra", color: "bg-slate-500/10 text-slate-400 ring-1 ring-slate-500/30", dot: "bg-slate-400" };

            return (
              <div
                key={rule.id}
                className={`flex items-center justify-between px-6 py-4 transition-opacity ${!rule.enabled ? "opacity-50" : ""}`}
              >
                <div className="flex items-center gap-3">
                  {rule.enabled ? (
                    rule.severity === "critical" ? (
                      <ShieldAlert className="h-5 w-5 shrink-0 text-red-500" />
                    ) : (
                      <ShieldCheck className="h-5 w-5 shrink-0 text-[var(--color-primary)]" />
                    )
                  ) : (
                    <ShieldOff className="h-5 w-5 shrink-0 text-[var(--color-text-muted)]" />
                  )}
                  <div>
                    <div className="text-sm font-medium text-[var(--color-text)]">{rule.name}</div>
                    <div className="text-xs text-[var(--color-text-muted)]">{rule.description}</div>
                  </div>
                </div>
                <div className="ml-4 flex shrink-0 items-center gap-3">
                  <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${consequence.color}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${consequence.dot}`} />
                    {consequence.label}
                  </span>
                  <Toggle enabled={rule.enabled} onChange={() => toggleSecurity(rule.id)} label={rule.name} />
                </div>
              </div>
            );
          })}
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
          <div className="flex items-center gap-2">
            {hasThresholdChanges && (
              <>
                <Badge variant="warning" dot>Não salvo</Badge>
                <button
                  onClick={() => setShowConfirmThreshold(true)}
                  className="flex cursor-pointer items-center gap-1.5 rounded-lg bg-[var(--color-cta)] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:opacity-90"
                >
                  Salvar limites
                </button>
              </>
            )}
            {thresholdSaved && (
              <Badge variant="success" dot>Salvo</Badge>
            )}
          </div>
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

      {/* Threshold Confirmation Modal */}
      {showConfirmThreshold && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-[var(--color-surface)] p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-[var(--color-text)]">Alterar limites de decisão?</h3>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">
              Esta mudança afetará como o ESTIXE avalia desvios e bloqueios a partir de agora.
            </p>

            {/* Impact summary in modal */}
            <div className="mt-4 space-y-2 rounded-lg bg-white/5 p-4 text-sm">
              <div className="flex justify-between items-center">
                <span className="text-[var(--color-text-muted)]">Confiança de desvio</span>
                <strong className="font-[family-name:var(--font-mono)] text-[var(--color-primary)]">
                  {bypassConfidence}%
                </strong>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-[var(--color-text-muted)]">Confiança de bloqueio</span>
                <strong className="font-[family-name:var(--font-mono)] text-[var(--color-primary)]">
                  {blockConfidence}%
                </strong>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-[var(--color-text-muted)]">Impacto em custo</span>
                <strong className={`font-[family-name:var(--font-mono)] ${Math.abs(bypassImpact + blockImpact) > 0 ? (bypassImpact + blockImpact < 0 ? "text-green-600" : "text-amber-600") : "text-[var(--color-text)]"}`}>
                  {(bypassImpact + blockImpact > 0 ? "+" : "")}{(bypassImpact + blockImpact).toFixed(1)}%
                </strong>
              </div>
            </div>

            {saveError && (
              <div className="mt-3 rounded-lg bg-red-950/50 px-3 py-2 text-xs text-red-400">
                {saveError}
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={handleCancelThreshold}
                className="cursor-pointer rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)]"
              >
                Cancelar
              </button>
              <button
                onClick={handleSaveThreshold}
                disabled={saving}
                className="cursor-pointer rounded-lg bg-[var(--color-cta)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
              >
                {saving ? "Salvando..." : "Aplicar limites"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
