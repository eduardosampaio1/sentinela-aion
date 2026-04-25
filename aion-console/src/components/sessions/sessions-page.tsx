"use client";

import { useState } from "react";
import {
  Shield,
  GitBranch,
  Gauge,
  CheckCircle2,
  ChevronRight,
  AlertTriangle,
  X,
  Bot,
  User,
  Cpu,
  Ban,
  Fingerprint,
  Minimize2,
  Flag,
  ThumbsUp,
  ThumbsDown,
  MessageSquare,
  Clock,
  UserCheck,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { TimeRangeSelect } from "@/components/ui/time-range-select";
import type { TimeRange } from "@/components/ui/time-range-select";
import { useApiData } from "@/lib/use-api-data";
import { getSessions, getApprovals, resolveApproval } from "@/lib/api";
import { DemoBanner } from "@/components/ui/demo-banner";
import { mockSessions, mockAnnotations } from "@/lib/mock-data";
import type { Session, SessionTurn, AnnotationItem } from "@/lib/types";

type PendingApproval = {
  id: string;
  session_id?: string;
  request_id?: string;
  risk_score?: number;
  summary?: string;
  created_at?: string | number;
  reason?: string;
};

const riskConfig: Record<string, { badge: "success" | "warning" | "error" | "muted"; label: string }> = {
  low: { badge: "success", label: "Baixo" },
  medium: { badge: "warning", label: "Médio" },
  high: { badge: "error", label: "Alto" },
  critical: { badge: "error", label: "Crítico" },
};

const outcomeConfig: Record<string, { label: string; color: string }> = {
  bypassed: { label: "Desviado", color: "text-teal-400" },
  routed: { label: "Roteado", color: "text-sky-400" },
  blocked: { label: "Bloqueado", color: "text-red-400" },
  optimized: { label: "Otimizado", color: "text-violet-400" },
};

const decisionConfig: Record<string, { label: string; color: string; bg: string }> = {
  bypass: { label: "bypass", color: "text-teal-400", bg: "bg-teal-900/30" },
  route: { label: "route", color: "text-sky-400", bg: "bg-sky-900/30" },
  block: { label: "block", color: "text-red-400", bg: "bg-red-900/30" },
  fallback: { label: "fallback", color: "text-amber-400", bg: "bg-amber-900/30" },
};

const moduleIcon = (module: string | null) => {
  switch (module) {
    case "ESTIXE": return <Shield className="h-3.5 w-3.5 text-teal-400" />;
    case "NOMOS": return <GitBranch className="h-3.5 w-3.5 text-sky-400" />;
    case "METIS": return <Gauge className="h-3.5 w-3.5 text-violet-400" />;
    default: return null;
  }
};

const riskBar = (score: number) => {
  const pct = Math.round(score * 100);
  const color = score < 0.3 ? "bg-green-500" : score < 0.6 ? "bg-amber-500" : "bg-red-500";
  return (
    <span className="flex items-center gap-1.5 ml-auto">
      <div className="h-1.5 w-12 rounded-full bg-white/10">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-[var(--color-text-muted)]">{pct}</span>
    </span>
  );
};

function TurnDetail({ turn }: { turn: SessionTurn }) {
  const d = decisionConfig[turn.decision];

  return (
    <div className="py-4 border-b border-[var(--color-border)]/40 last:border-0 space-y-3">
      {/* Turn number + timestamp */}
      <div className="flex items-center gap-2">
        <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-[10px] font-bold text-[var(--color-text-muted)]">
          {turn.turn}
        </div>
        <span className="text-[10px] text-[var(--color-text-muted)]">
          {new Date(turn.timestamp).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </span>
        <div className="flex items-center gap-2 ml-auto">
          {turn.pii_detected && turn.pii_detected.length > 0 && (
            <span className="flex items-center gap-1 rounded bg-amber-900/30 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
              <Fingerprint className="h-3 w-3" />
              {turn.pii_detected.join(", ")}
            </span>
          )}
          {turn.metis_compressed && (
            <span className="flex items-center gap-1 rounded bg-violet-900/30 px-1.5 py-0.5 text-[10px] font-medium text-violet-400">
              <Minimize2 className="h-3 w-3" />
              METIS
            </span>
          )}
        </div>
      </div>

      {/* User message */}
      <div className="flex gap-2.5">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10">
          <User className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
        </div>
        <div className="flex-1 rounded-xl rounded-tl-none bg-white/5 px-3 py-2">
          <p className="text-sm text-[var(--color-text)] leading-relaxed">{turn.input}</p>
        </div>
      </div>

      {/* Decision metadata */}
      <div className="flex items-center gap-2 pl-8 text-xs">
        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium ${d.bg} ${d.color}`}>
          {d.label}
        </span>
        {turn.module && (
          <span className="flex items-center gap-1 text-[var(--color-text-muted)]">
            {moduleIcon(turn.module)}
            {turn.module}
          </span>
        )}
        {turn.model_used && (
          <span className="flex items-center gap-1 font-[family-name:var(--font-mono)] text-[var(--color-text-muted)]">
            <Cpu className="h-3 w-3" />
            {turn.model_used}
          </span>
        )}
        <span className="text-[var(--color-text-muted)]">{turn.latency_ms}ms</span>
        {turn.cost > 0 && (
          <span className="text-[var(--color-text-muted)]">${turn.cost.toFixed(4)}</span>
        )}
        {riskBar(turn.risk_score)}
      </div>

      {/* Response — AION bypass */}
      {turn.aion_response && (
        <div className="flex gap-2.5 pl-4">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-teal-900/50">
            <Bot className="h-3.5 w-3.5 text-teal-400" />
          </div>
          <div className="flex-1 rounded-xl rounded-tl-none border border-teal-800/30 bg-teal-950/30 px-3 py-2">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-teal-600">AION — bypass</p>
            <p className="text-sm text-[var(--color-text)] leading-relaxed whitespace-pre-line">{turn.aion_response}</p>
          </div>
        </div>
      )}

      {/* Response — LLM route */}
      {turn.llm_response && (
        <div className="flex gap-2.5 pl-4">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-900/50">
            <Cpu className="h-3.5 w-3.5 text-sky-400" />
          </div>
          <div className="flex-1 rounded-xl rounded-tl-none border border-sky-800/30 bg-sky-950/20 px-3 py-2">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-sky-600">
              {turn.model_used ?? "LLM"} — via NOMOS
            </p>
            <p className="text-sm text-[var(--color-text)] leading-relaxed whitespace-pre-line">{turn.llm_response}</p>
          </div>
        </div>
      )}

      {/* Response — BLOCK */}
      {turn.block_reason && (
        <div className="flex gap-2.5 pl-4">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-red-900/50">
            <Ban className="h-3.5 w-3.5 text-red-400" />
          </div>
          <div className="flex-1 rounded-xl rounded-tl-none border border-red-800/40 bg-red-950/30 px-3 py-2">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-red-500">ESTIXE — bloqueado</p>
            <p className="text-sm text-red-300 leading-relaxed">{turn.block_reason}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function SessionDrawer({ session, onClose }: { session: Session; onClose: () => void }) {
  const risk = riskConfig[session.risk];
  const outcome = outcomeConfig[session.outcome];

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
      />

      {/* Drawer */}
      <aside className="fixed inset-y-0 right-0 z-40 flex w-[480px] flex-col border-l border-[var(--color-border)] bg-[var(--color-surface)] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-[var(--color-text)] font-[family-name:var(--font-mono)]">
              {session.id}
            </p>
            <p className="text-xs text-[var(--color-text-muted)]">{session.user_hash}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-white/10 hover:text-[var(--color-text)] transition-colors"
            aria-label="Fechar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Status row */}
        <div className="flex items-center gap-4 border-b border-[var(--color-border)] px-5 py-3">
          <Badge variant={risk.badge}>{risk.label}</Badge>
          <span className={`text-sm font-medium ${outcome.color}`}>{outcome.label}</span>
          <div className="ml-auto flex items-center gap-1.5 text-xs">
            {session.hmac_valid ? (
              <><CheckCircle2 className="h-3.5 w-3.5 text-green-400" /><span className="text-green-400">HMAC válido</span></>
            ) : (
              <><AlertTriangle className="h-3.5 w-3.5 text-red-400" /><span className="text-red-400">HMAC inválido</span></>
            )}
          </div>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-3 divide-x divide-[var(--color-border)] border-b border-[var(--color-border)]">
          <div className="px-5 py-3">
            <p className="text-xs text-[var(--color-text-muted)]">Turnos</p>
            <p className="mt-0.5 text-xl font-bold text-[var(--color-text)]">{session.turns}</p>
          </div>
          <div className="px-5 py-3">
            <p className="text-xs text-[var(--color-text-muted)]">Gasto</p>
            <p className="mt-0.5 text-xl font-bold text-[var(--color-text)]">${session.spend.toFixed(4)}</p>
          </div>
          <div className="px-5 py-3">
            <p className="text-xs text-[var(--color-text-muted)]">Tenant</p>
            <p className="mt-0.5 text-sm font-bold text-[var(--color-text)]">{session.tenant}</p>
          </div>
        </div>

        {/* Turn history */}
        <div className="flex-1 overflow-y-auto px-5 py-2">
          {session.turn_history.length > 0 ? (
            session.turn_history.map((t) => <TurnDetail key={t.turn} turn={t} />)
          ) : (
            <p className="py-10 text-center text-sm text-[var(--color-text-muted)]">
              Histórico não disponível para esta sessão
            </p>
          )}
        </div>
      </aside>
    </>
  );
}

function getQualityBadge(s: Session): { variant: "error" | "warning" | "muted" | "success"; label: string } {
  if (s.hmac_valid === false) return { variant: "error", label: "Revisar" };
  if (s.risk === "critical") return { variant: "warning", label: "Pendente" };
  if (s.outcome === "blocked" && s.hmac_valid) return { variant: "muted", label: "Bloqueada" };
  return { variant: "success", label: "OK" };
}

function AnnotationCard({
  item,
  state,
  setState,
}: {
  item: AnnotationItem;
  state: {
    decision_correct?: boolean;
    false_positive?: boolean;
    response_adequate?: boolean;
    comment: string;
    submitted: boolean;
  };
  setState: (next: typeof state) => void;
}) {
  const isAnnotated = item.annotated || state.submitted;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 mb-3">
      {/* Top row */}
      <div className="flex items-start gap-3 mb-3">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--color-primary)] shrink-0">
            {item.session_id}
          </span>
          <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-white/10 text-[10px] font-bold text-[var(--color-text-muted)] shrink-0">
            {item.turn}
          </span>
          <span className="flex items-center gap-1 text-xs text-amber-400 truncate">
            <AlertTriangle className="h-3 w-3 shrink-0" />
            {item.flagged_reason}
          </span>
        </div>
        {isAnnotated && (
          <span className="flex items-center gap-1 rounded-full bg-green-900/30 px-2.5 py-0.5 text-xs font-medium text-green-400 shrink-0">
            <CheckCircle2 className="h-3 w-3" />
            Anotada
          </span>
        )}
      </div>

      {/* Prompt box */}
      <div className="rounded-lg bg-white/5 p-3 mb-3">
        <p className="text-sm text-[var(--color-text)] leading-relaxed">{item.prompt}</p>
      </div>

      {/* AION response / block reason */}
      {item.aion_response && (
        <div className="flex gap-2 mb-3">
          <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-teal-900/50 mt-0.5">
            <Bot className="h-3 w-3 text-teal-400" />
          </div>
          <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">{item.aion_response}</p>
        </div>
      )}
      {item.block_reason && (
        <div className="flex gap-2 mb-3">
          <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-900/50 mt-0.5">
            <Ban className="h-3 w-3 text-red-400" />
          </div>
          <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">{item.block_reason}</p>
        </div>
      )}

      {/* Controls or read-only summary */}
      {!isAnnotated ? (
        <div className="border-t border-[var(--color-border)]/50 pt-3 space-y-3">
          {/* Decisão correta? */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-[var(--color-text-muted)] w-36 shrink-0">Decisão correta?</span>
            <div className="flex gap-2">
              <button
                onClick={() => setState({ ...state, decision_correct: true })}
                className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  state.decision_correct === true
                    ? "bg-green-900/40 text-green-400 ring-1 ring-green-600/50"
                    : "bg-white/5 text-[var(--color-text-muted)] hover:text-green-400"
                }`}
              >
                <ThumbsUp className="h-3 w-3" />
                Correta
              </button>
              <button
                onClick={() => setState({ ...state, decision_correct: false })}
                className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  state.decision_correct === false
                    ? "bg-red-900/40 text-red-400 ring-1 ring-red-600/50"
                    : "bg-white/5 text-[var(--color-text-muted)] hover:text-red-400"
                }`}
              >
                <ThumbsDown className="h-3 w-3" />
                Incorreta
              </button>
            </div>
          </div>

          {/* Falso positivo? */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-[var(--color-text-muted)] w-36 shrink-0">Falso positivo?</span>
            <div className="flex gap-2">
              <button
                onClick={() => setState({ ...state, false_positive: true })}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  state.false_positive === true
                    ? "bg-amber-900/40 text-amber-400 ring-1 ring-amber-600/50"
                    : "bg-white/5 text-[var(--color-text-muted)] hover:text-amber-400"
                }`}
              >
                Sim
              </button>
              <button
                onClick={() => setState({ ...state, false_positive: false })}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  state.false_positive === false
                    ? "bg-white/15 text-[var(--color-text)] ring-1 ring-white/20"
                    : "bg-white/5 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                }`}
              >
                Não
              </button>
            </div>
          </div>

          {/* Resposta adequada? — only if has aion_response */}
          {item.aion_response && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-[var(--color-text-muted)] w-36 shrink-0">Resposta adequada?</span>
              <div className="flex gap-2">
                <button
                  onClick={() => setState({ ...state, response_adequate: true })}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                    state.response_adequate === true
                      ? "bg-green-900/40 text-green-400 ring-1 ring-green-600/50"
                      : "bg-white/5 text-[var(--color-text-muted)] hover:text-green-400"
                  }`}
                >
                  Adequada
                </button>
                <button
                  onClick={() => setState({ ...state, response_adequate: false })}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                    state.response_adequate === false
                      ? "bg-red-900/40 text-red-400 ring-1 ring-red-600/50"
                      : "bg-white/5 text-[var(--color-text-muted)] hover:text-red-400"
                  }`}
                >
                  Inadequada
                </button>
              </div>
            </div>
          )}

          {/* Comment */}
          <div className="flex items-start gap-3">
            <span className="text-xs text-[var(--color-text-muted)] w-36 shrink-0 pt-1.5">Comentário</span>
            <textarea
              value={state.comment}
              onChange={(e) => setState({ ...state, comment: e.target.value })}
              placeholder="Opcional..."
              rows={2}
              className="flex-1 rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] resize-none focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]/50"
            />
          </div>

          {/* Submit */}
          <div className="flex justify-end">
            <button
              onClick={() => setState({ ...state, submitted: true })}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--color-cta)] px-4 py-1.5 text-xs font-semibold text-white hover:opacity-90 transition-opacity"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Enviar anotação
            </button>
          </div>
        </div>
      ) : (
        <div className="border-t border-[var(--color-border)]/50 pt-3">
          <div className="flex flex-wrap gap-2 text-xs">
            {(item.decision_correct !== undefined || state.decision_correct !== undefined) && (
              <span className={`rounded-full px-2.5 py-0.5 font-medium ${
                (state.submitted ? state.decision_correct : item.decision_correct)
                  ? "bg-green-900/30 text-green-400"
                  : "bg-red-900/30 text-red-400"
              }`}>
                Decisão: {(state.submitted ? state.decision_correct : item.decision_correct) ? "Correta" : "Incorreta"}
              </span>
            )}
            {(item.false_positive !== undefined || state.false_positive !== undefined) && (
              <span className="rounded-full bg-white/10 px-2.5 py-0.5 font-medium text-[var(--color-text-muted)]">
                Falso positivo: {(state.submitted ? state.false_positive : item.false_positive) ? "Sim" : "Não"}
              </span>
            )}
            {(item.response_adequate !== undefined || state.response_adequate !== undefined) && (
              <span className={`rounded-full px-2.5 py-0.5 font-medium ${
                (state.submitted ? state.response_adequate : item.response_adequate)
                  ? "bg-green-900/30 text-green-400"
                  : "bg-red-900/30 text-red-400"
              }`}>
                Resposta: {(state.submitted ? state.response_adequate : item.response_adequate) ? "Adequada" : "Inadequada"}
              </span>
            )}
            {(item.comment || state.comment) && (
              <span className="text-[var(--color-text-muted)] italic">
                "{state.submitted ? state.comment : item.comment}"
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function SessionsPage() {
  const [selected, setSelected] = useState<Session | null>(null);
  const [filter, setFilter] = useState<"all" | "high" | "critical" | "blocked">("all");
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [activeTab, setActiveTab] = useState<"sessions" | "annotations" | "approvals">("sessions");
  const [annotationState, setAnnotationState] = useState<Record<string, {
    decision_correct?: boolean;
    false_positive?: boolean;
    response_adequate?: boolean;
    comment: string;
    submitted: boolean;
  }>>({});

  // Approvals state
  const { data: approvalsRaw, isDemo: approvalsIsDemo, refetch: refetchApprovals } = useApiData(
    () => getApprovals("pending"),
    [] as Record<string, unknown>[],
    { intervalMs: 15_000 },
  );
  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set());
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolveAction, setResolveAction] = useState<"approved" | "denied" | null>(null);
  const [approverInput, setApproverInput] = useState("");
  const [resolving, setResolving] = useState(false);

  const approvals: PendingApproval[] = (approvalsRaw as Record<string, unknown>[])
    .map((a) => ({
      id: String(a.id ?? a.approval_id ?? ""),
      session_id: a.session_id as string | undefined,
      request_id: a.request_id as string | undefined,
      risk_score: typeof a.risk_score === "number" ? a.risk_score : undefined,
      summary: a.summary as string | undefined,
      created_at: a.created_at as string | number | undefined,
      reason: a.reason as string | undefined,
    }))
    .filter((a) => a.id && !resolvedIds.has(a.id));

  function startResolve(id: string, action: "approved" | "denied") {
    setResolvingId(id);
    setResolveAction(action);
    setApproverInput("");
  }

  function cancelResolve() {
    setResolvingId(null);
    setResolveAction(null);
    setApproverInput("");
  }

  async function confirmResolve() {
    if (!resolvingId || !resolveAction) return;
    setResolving(true);
    try {
      await resolveApproval(resolvingId, resolveAction, approverInput.trim() || "operador");
      setResolvedIds((prev) => new Set(prev).add(resolvingId));
      cancelResolve();
      refetchApprovals();
    } catch {
      // keep UI open, let user retry
    } finally {
      setResolving(false);
    }
  }

  const { data: sessions, isDemo, refetch } = useApiData(getSessions, mockSessions, {
    intervalMs: 30_000,
  });

  const filtered = sessions.filter((s) => {
    if (filter === "all") return true;
    if (filter === "blocked") return s.outcome === "blocked";
    return s.risk === filter;
  });

  const pendingCount = mockAnnotations.filter(
    (a) => !a.annotated && !annotationState[a.id]?.submitted,
  ).length;
  const annotatedCount = mockAnnotations.filter(
    (a) => a.annotated || annotationState[a.id]?.submitted,
  ).length;

  const getAnnState = (id: string) =>
    annotationState[id] ?? { comment: "", submitted: false };

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner onRetry={refetch} />}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            Sessões
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Histórico de conversas com auditoria turn-by-turn
          </p>
        </div>
        {activeTab === "sessions" && (
          <div className="flex items-center gap-2">
            <TimeRangeSelect value={timeRange} onChange={setTimeRange} />
            {(["all", "high", "critical", "blocked"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                  filter === f
                    ? "bg-[var(--color-primary)]/20 text-[var(--color-primary)]"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                }`}
              >
                {f === "all" ? "Todas" : f === "high" ? "Alto risco" : f === "critical" ? "Crítico" : "Bloqueadas"}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 border-b border-[var(--color-border)]">
        {(["sessions", "annotations", "approvals"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium transition-colors relative ${
              activeTab === tab
                ? "text-[var(--color-text)]"
                : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tab === "sessions" ? "Sessões" : tab === "annotations" ? "Anotações" : "Aprovações"}
            {activeTab === tab && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--color-primary)] rounded-t-full" />
            )}
            {tab === "annotations" && pendingCount > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-4 px-1 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-bold">
                {pendingCount}
              </span>
            )}
            {tab === "approvals" && approvals.length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-4 px-1 rounded-full bg-orange-500/25 text-orange-400 text-[10px] font-bold">
                {approvals.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Sessions tab */}
      {activeTab === "sessions" && (
        <>
          {/* Table — full width, no split */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-border)]">
                    {["Sessão", "Usuário", "Turnos", "Risco", "Outcome", "Gasto", "HMAC", "Qualidade", ""].map((h) => (
                      <th key={h} className="px-5 py-3 text-left text-xs font-medium text-[var(--color-text-muted)]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((s) => {
                    const risk = riskConfig[s.risk];
                    const outcome = outcomeConfig[s.outcome];
                    const quality = getQualityBadge(s);
                    const isActive = selected?.id === s.id;
                    return (
                      <tr
                        key={s.id}
                        onClick={() => setSelected(s)}
                        className={`cursor-pointer border-b border-[var(--color-border)]/50 transition-colors ${
                          isActive
                            ? "bg-[var(--color-primary)]/5"
                            : "hover:bg-white/5"
                        }`}
                      >
                        <td className="px-5 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-primary)]">
                          {s.id}
                        </td>
                        <td className="px-5 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                          {s.user_hash}
                        </td>
                        <td className="px-5 py-3 text-center text-[var(--color-text)]">{s.turns}</td>
                        <td className="px-5 py-3">
                          <Badge variant={risk.badge}>{risk.label}</Badge>
                        </td>
                        <td className={`px-5 py-3 text-sm font-medium ${outcome.color}`}>
                          {outcome.label}
                        </td>
                        <td className="px-5 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                          ${s.spend.toFixed(4)}
                        </td>
                        <td className="px-5 py-3">
                          {s.hmac_valid ? (
                            <CheckCircle2 className="h-4 w-4 text-green-400" />
                          ) : (
                            <AlertTriangle className="h-4 w-4 text-amber-400" />
                          )}
                        </td>
                        <td className="px-5 py-3">
                          <Badge variant={quality.variant}>{quality.label}</Badge>
                        </td>
                        <td className="px-5 py-3">
                          <ChevronRight className={`h-4 w-4 transition-colors ${isActive ? "text-[var(--color-primary)]" : "text-[var(--color-text-muted)]"}`} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Drawer — slides over the page */}
          {selected && (
            <SessionDrawer
              session={selected}
              onClose={() => setSelected(null)}
            />
          )}
        </>
      )}

      {/* Annotations tab */}
      {activeTab === "annotations" && (
        <div>
          {/* Header row */}
          <div className="flex items-center gap-1.5 mb-4 text-sm text-[var(--color-text-muted)]">
            <Flag className="h-4 w-4 text-amber-400" />
            <span>
              <span className="font-semibold text-[var(--color-text)]">{pendingCount}</span> pendentes de revisão
              {" · "}
              <span className="font-semibold text-[var(--color-text)]">{annotatedCount}</span> anotadas
            </span>
          </div>

          {mockAnnotations.map((item) => (
            <AnnotationCard
              key={item.id}
              item={item}
              state={getAnnState(item.id)}
              setState={(next) =>
                setAnnotationState((prev) => ({ ...prev, [item.id]: next }))
              }
            />
          ))}
        </div>
      )}

      {/* Approvals tab */}
      {activeTab === "approvals" && (
        <div className="space-y-3">
          {approvalsIsDemo && <DemoBanner onRetry={refetchApprovals} />}

          {/* Header row */}
          <div className="flex items-center gap-1.5 text-sm text-[var(--color-text-muted)]">
            <Clock className="h-4 w-4 text-orange-400" />
            <span>
              <span className="font-semibold text-[var(--color-text)]">{approvals.length}</span>{" "}
              decisões pendentes de aprovação humana
            </span>
          </div>

          {/* Empty state */}
          {approvals.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-16 text-center">
              <CheckCircle2 className="h-8 w-8 text-green-400 mb-3" />
              <p className="text-sm font-medium text-[var(--color-text)]">Nenhuma aprovação pendente</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                Todas as decisões de alto risco foram revisadas
              </p>
            </div>
          )}

          {/* Approval cards */}
          {approvals.map((apv) => {
            const isExpanded = resolvingId === apv.id;
            const riskPct = apv.risk_score != null ? Math.round(apv.risk_score * 100) : null;
            const riskColor =
              apv.risk_score == null
                ? "text-[var(--color-text-muted)]"
                : apv.risk_score >= 0.7
                ? "text-red-400"
                : apv.risk_score >= 0.4
                ? "text-amber-400"
                : "text-green-400";
            const createdAt =
              apv.created_at
                ? new Date(
                    typeof apv.created_at === "number" ? apv.created_at * 1000 : apv.created_at,
                  ).toLocaleString("pt-BR", {
                    day: "2-digit",
                    month: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : null;

            return (
              <div
                key={apv.id}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden"
              >
                {/* Card header */}
                <div className="flex items-start gap-3 px-5 py-4">
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--color-primary)]">
                        {apv.request_id ?? apv.id}
                      </span>
                      {apv.session_id && (
                        <span className="text-[10px] text-[var(--color-text-muted)] bg-white/5 rounded px-1.5 py-0.5">
                          sessão {apv.session_id}
                        </span>
                      )}
                      {createdAt && (
                        <span className="flex items-center gap-1 text-[10px] text-[var(--color-text-muted)]">
                          <Clock className="h-3 w-3" />
                          {createdAt}
                        </span>
                      )}
                    </div>
                    {apv.summary && (
                      <p className="text-sm text-[var(--color-text)] leading-snug">{apv.summary}</p>
                    )}
                    {apv.reason && (
                      <p className="text-xs text-[var(--color-text-muted)] leading-snug italic">
                        Motivo: {apv.reason}
                      </p>
                    )}
                  </div>

                  {/* Risk score pill */}
                  {riskPct != null && (
                    <div className="shrink-0 flex flex-col items-end gap-1">
                      <span className={`text-sm font-bold tabular-nums ${riskColor}`}>
                        {riskPct}
                      </span>
                      <div className="h-1.5 w-16 rounded-full bg-white/10">
                        <div
                          className={`h-1.5 rounded-full ${
                            apv.risk_score! >= 0.7
                              ? "bg-red-500"
                              : apv.risk_score! >= 0.4
                              ? "bg-amber-500"
                              : "bg-green-500"
                          }`}
                          style={{ width: `${riskPct}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* Action row — collapsed */}
                {!isExpanded && (
                  <div className="flex items-center gap-2 border-t border-[var(--color-border)]/50 px-5 py-3 bg-white/[0.02]">
                    <button
                      onClick={() => startResolve(apv.id, "approved")}
                      className="flex items-center gap-1.5 rounded-lg bg-green-900/30 px-3 py-1.5 text-xs font-semibold text-green-400 hover:bg-green-900/50 transition-colors"
                    >
                      <UserCheck className="h-3.5 w-3.5" />
                      Aprovar
                    </button>
                    <button
                      onClick={() => startResolve(apv.id, "denied")}
                      className="flex items-center gap-1.5 rounded-lg bg-red-900/30 px-3 py-1.5 text-xs font-semibold text-red-400 hover:bg-red-900/50 transition-colors"
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      Negar
                    </button>
                  </div>
                )}

                {/* Inline confirm row — expanded */}
                {isExpanded && (
                  <div
                    className={`border-t px-5 py-4 space-y-3 ${
                      resolveAction === "approved"
                        ? "border-green-800/40 bg-green-950/20"
                        : "border-red-800/40 bg-red-950/20"
                    }`}
                  >
                    <p className={`text-xs font-semibold ${resolveAction === "approved" ? "text-green-400" : "text-red-400"}`}>
                      {resolveAction === "approved" ? "✓ Confirmar aprovação" : "✗ Confirmar negação"}
                    </p>
                    <div className="flex items-center gap-2">
                      <input
                        autoFocus
                        value={approverInput}
                        onChange={(e) => setApproverInput(e.target.value)}
                        placeholder="Seu nome (aprovador)"
                        className="flex-1 rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-1.5 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]/50"
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !resolving) confirmResolve();
                          if (e.key === "Escape") cancelResolve();
                        }}
                      />
                      <button
                        onClick={confirmResolve}
                        disabled={resolving}
                        className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50 ${
                          resolveAction === "approved"
                            ? "bg-green-700/50 text-green-300 hover:bg-green-700/70"
                            : "bg-red-700/50 text-red-300 hover:bg-red-700/70"
                        }`}
                      >
                        {resolving ? (
                          <span className="animate-spin h-3.5 w-3.5 border border-current rounded-full border-t-transparent" />
                        ) : resolveAction === "approved" ? (
                          <UserCheck className="h-3.5 w-3.5" />
                        ) : (
                          <XCircle className="h-3.5 w-3.5" />
                        )}
                        {resolving ? "Salvando…" : "Confirmar"}
                      </button>
                      <button
                        onClick={cancelResolve}
                        disabled={resolving}
                        className="rounded-lg px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-white/5 transition-colors disabled:opacity-50"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
