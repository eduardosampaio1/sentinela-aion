"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Scale,
  FlaskConical,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Plus,
  ArrowLeft,
  Clock,
  User,
  Activity,
  PlayCircle,
  AlertCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/demo-banner";
import { ConfirmActionModal } from "@/components/ui/confirm-action-modal";
import { useApiData } from "@/lib/use-api-data";
import {
  getKairosTemplates,
  getKairosCandidates,
  getKairosCandidate,
  createCandidateFromTemplate,
  markCandidateReady,
  startKairosShadow,
  approveKairosCandidate,
  rejectKairosCandidate,
  type PolicyTemplate,
  type PolicyCandidate,
  type CandidateDetail,
  type PolicyCandidateStatus,
  type LifecycleEvent,
  type ShadowRun,
} from "@/lib/api/kairos";

// ── Mock data (shown when backend is unavailable) ─────────────────────────

const MOCK_TEMPLATES: PolicyTemplate[] = [
  { id: "greeting_bypass", vertical: "financeiro", type: "bypass", title: "Bypass de saudações genéricas", description: "Responde saudações simples sem acionar o LLM." },
  { id: "boleto_second_copy_route_to_api", vertical: "financeiro", type: "route_to_api", title: "Segunda via de boleto → API interna", description: "Roteamento direto para a API de faturamento." },
  { id: "pix_sensitive_data_guard", vertical: "financeiro", type: "guardrail", title: "Guardrail: dados sensíveis em PIX", description: "Bloqueia transmissão de dados PIX sensíveis." },
];

const MOCK_CANDIDATES: PolicyCandidate[] = [
  {
    id: "cand-001",
    tenant_id: "default",
    template_id: "boleto_second_copy_route_to_api",
    type: "route_to_api",
    status: "shadow_completed",
    title: "Segunda via de boleto → API interna",
    business_summary: "Clientes que solicitam segunda via de boleto são roteados diretamente para a API interna de faturamento, reduzindo latência e custo de LLM.",
    technical_summary: "trigger: intent=segunda_via_boleto, confidence≥0.82. action: route_to_api billing_api.second_copy. fallback: model_tier low_cost_fast.",
    trigger_conditions: [{ field: "intent", operator: "equals", value: "segunda_via_boleto" }],
    proposed_actions: [],
    created_at: "2026-04-28T10:00:00Z",
    updated_at: "2026-05-05T14:30:00Z",
    shadow_run_id: "run-001",
    approved_by: null,
    approved_at: null,
    rejection_reason: null,
  },
  {
    id: "cand-002",
    tenant_id: "default",
    template_id: "greeting_bypass",
    type: "bypass",
    status: "shadow_running",
    title: "Bypass de saudações genéricas",
    business_summary: "Saudações simples (oi, olá, bom dia) respondem sem acionar o LLM, economizando tokens e reduzindo latência.",
    technical_summary: "trigger: intent_pattern ^(oi|olá|bom dia|boa tarde|boa noite), confidence≥0.92. action: bypass_llm response_template greeting_standard.",
    trigger_conditions: [{ field: "intent", operator: "matches_pattern", value: "^(oi|olá|bom dia|boa tarde|boa noite)" }],
    proposed_actions: [],
    created_at: "2026-05-01T09:00:00Z",
    updated_at: "2026-05-06T08:00:00Z",
    shadow_run_id: "run-002",
    approved_by: null,
    approved_at: null,
    rejection_reason: null,
  },
  {
    id: "cand-003",
    tenant_id: "default",
    template_id: "pix_sensitive_data_guard",
    type: "guardrail",
    status: "draft",
    title: "Guardrail: dados sensíveis em PIX",
    business_summary: "Bloqueia qualquer mensagem que contenha chaves PIX, CPF ou CNPJ em contexto de transação, prevenindo vazamento de dados.",
    technical_summary: "trigger: pii_detected=true AND context=pix_transaction. action: block reason pii_in_pix_context. fallback: capability safe_response.",
    trigger_conditions: [{ field: "pii_detected", operator: "equals", value: true }],
    proposed_actions: [],
    created_at: "2026-05-06T11:00:00Z",
    updated_at: "2026-05-06T11:00:00Z",
    shadow_run_id: null,
    approved_by: null,
    approved_at: null,
    rejection_reason: null,
  },
];

// Build a mock CandidateDetail that matches the candidate's actual status/id
function buildMockDetail(candidate: PolicyCandidate): CandidateDetail {
  const events: LifecycleEvent[] = [
    { id: `${candidate.id}-e1`, candidate_id: candidate.id, from_status: null, to_status: "draft", actor_type: "system", actor_id: null, reason: "created_from_template", metadata: {}, created_at: candidate.created_at },
  ];
  const statusOrder: PolicyCandidateStatus[] = ["draft", "ready_for_shadow", "shadow_running", "shadow_completed", "approved_production"];
  const idx = statusOrder.indexOf(candidate.status);
  if (idx >= 1) events.push({ id: `${candidate.id}-e2`, candidate_id: candidate.id, from_status: "draft", to_status: "ready_for_shadow", actor_type: "operator", actor_id: null, reason: "marked_ready_for_shadow", metadata: {}, created_at: candidate.created_at });
  if (idx >= 2) events.push({ id: `${candidate.id}-e3`, candidate_id: candidate.id, from_status: "ready_for_shadow", to_status: "shadow_running", actor_type: "operator", actor_id: null, reason: "shadow_run_started", metadata: {}, created_at: candidate.updated_at });
  if (idx >= 3) events.push({ id: `${candidate.id}-e4`, candidate_id: candidate.id, from_status: "shadow_running", to_status: "shadow_completed", actor_type: "sweep", actor_id: null, reason: "min_observations_reached", metadata: {}, created_at: candidate.updated_at });
  if (idx >= 4) events.push({ id: `${candidate.id}-e5`, candidate_id: candidate.id, from_status: "shadow_completed", to_status: "approved_production", actor_type: "operator", actor_id: null, reason: "approved", metadata: {}, created_at: candidate.updated_at });
  if (candidate.status === "rejected") events.push({ id: `${candidate.id}-er`, candidate_id: candidate.id, from_status: "shadow_completed", to_status: "rejected", actor_type: "operator", actor_id: null, reason: candidate.rejection_reason ?? null, metadata: {}, created_at: candidate.updated_at });

  const hasShadow = ["shadow_running", "shadow_completed", "approved_production"].includes(candidate.status);
  const shadowRun: ShadowRun | null = hasShadow
    ? {
        id: candidate.shadow_run_id ?? `run-mock-${candidate.id}`,
        status: candidate.status === "shadow_running" ? "running" : "completed",
        observations_count: 1240,
        matched_count: 986,
        fallback_count: 42,
        started_at: candidate.created_at,
        completed_at: candidate.status === "shadow_running" ? null : candidate.updated_at,
        summary: candidate.status === "shadow_running" ? null : { observations: 1240, matched: 986, fallback: 42, match_rate: 0.7952, fallback_rate: 0.0339 },
      }
    : null;

  return { ...candidate, lifecycle_events: events, shadow_run: shadowRun };
}

// ── Status helpers ─────────────────────────────────────────────────────────

const STATUS_LABELS: Record<PolicyCandidateStatus, string> = {
  draft: "Rascunho",
  ready_for_shadow: "Pronto para Shadow",
  shadow_running: "Shadow em execução",
  shadow_completed: "Shadow concluído",
  approved_production: "Aprovado — Produção",
  under_review: "Em revisão",
  rejected: "Rejeitado",
  deprecated: "Descontinuado",
  archived: "Arquivado",
};

const STATUS_BADGE_VARIANT: Record<PolicyCandidateStatus, "default" | "success" | "warning" | "error" | "info" | "muted"> = {
  draft: "muted",
  ready_for_shadow: "info",
  shadow_running: "warning",
  shadow_completed: "info",
  approved_production: "success",
  under_review: "warning",
  rejected: "error",
  deprecated: "muted",
  archived: "muted",
};

const TYPE_LABELS: Record<string, string> = {
  bypass: "Bypass",
  guardrail: "Guardrail",
  route_to_api: "Route to API",
  handoff: "Handoff",
};

function StatusBadge({ status }: { status: PolicyCandidateStatus }) {
  return (
    <Badge variant={STATUS_BADGE_VARIANT[status]}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}

function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    bypass: "bg-violet-900/30 text-violet-400",
    guardrail: "bg-red-900/30 text-red-400",
    route_to_api: "bg-blue-900/30 text-blue-400",
    handoff: "bg-amber-900/30 text-amber-400",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${colors[type] ?? "bg-white/10 text-slate-300"}`}>
      {TYPE_LABELS[type] ?? type}
    </span>
  );
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtTriggerValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// ── LifecycleTimeline ──────────────────────────────────────────────────────

function LifecycleTimeline({ events }: { events: LifecycleEvent[] }) {
  if (events.length === 0) {
    return <p className="text-xs text-[var(--color-text-muted)]">Nenhum evento registrado.</p>;
  }

  return (
    <ol className="relative space-y-0 border-l border-[var(--color-border)] pl-5">
      {events.map((ev, idx) => {
        const isLast = idx === events.length - 1;
        return (
          <li key={ev.id} className={`relative ${isLast ? "pb-0" : "pb-5"}`}>
            <span className="absolute -left-[21px] flex h-4 w-4 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]" />
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={ev.to_status as PolicyCandidateStatus} />
              <span className="text-xs text-[var(--color-text-muted)]">{fmtDate(ev.created_at)}</span>
              {ev.actor_type && (
                <span className="inline-flex items-center gap-1 rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)]">
                  <User className="h-2.5 w-2.5" />
                  {ev.actor_type}
                </span>
              )}
              {ev.reason && (
                <span className="font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-text-muted)]/70">
                  {ev.reason}
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ── ShadowResult ───────────────────────────────────────────────────────────

function ShadowResult({ run }: { run: ShadowRun }) {
  const pct = (n: number) => (n * 100).toFixed(1) + "%";
  const matchRate = run.summary?.match_rate ?? (run.observations_count > 0 ? run.matched_count / run.observations_count : 0);
  const fallbackRate = run.summary?.fallback_rate ?? (run.observations_count > 0 ? run.fallback_count / run.observations_count : 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-violet-400" />
        <span className="text-sm font-semibold text-[var(--color-text)]">Resultado do Shadow Run</span>
        <Badge variant={run.status === "running" ? "warning" : run.status === "completed" ? "success" : "error"} dot pulse={run.status === "running"}>
          {run.status === "running" ? "em execução" : run.status === "completed" ? "concluído" : "falhou"}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-white/5 px-4 py-3">
          <p className="text-xs text-[var(--color-text-muted)]">Observações</p>
          <p className="mt-1 font-[family-name:var(--font-mono)] text-xl font-bold text-[var(--color-text)]">
            {run.observations_count.toLocaleString("pt-BR")}
          </p>
        </div>
        <div className="rounded-lg bg-white/5 px-4 py-3">
          <p className="text-xs text-[var(--color-text-muted)]">Taxa de match</p>
          <p className={`mt-1 font-[family-name:var(--font-mono)] text-xl font-bold ${matchRate >= 0.7 ? "text-green-400" : matchRate >= 0.5 ? "text-amber-400" : "text-red-400"}`}>
            {pct(matchRate)}
          </p>
        </div>
        <div className="rounded-lg bg-white/5 px-4 py-3">
          <p className="text-xs text-[var(--color-text-muted)]">Fallback rate</p>
          <p className={`mt-1 font-[family-name:var(--font-mono)] text-xl font-bold ${fallbackRate <= 0.05 ? "text-green-400" : fallbackRate <= 0.15 ? "text-amber-400" : "text-red-400"}`}>
            {pct(fallbackRate)}
          </p>
        </div>
      </div>

      {run.status === "running" && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-800/40 bg-amber-950/20 px-4 py-3 text-sm text-amber-300">
          <Activity className="h-4 w-4 shrink-0" />
          Shadow run em execução. O sweep finalizará automaticamente ao atingir o mínimo de observações ou expirar o prazo.
        </div>
      )}

      {run.status === "completed" && matchRate >= 0.7 && fallbackRate <= 0.1 && (
        <div className="flex items-center gap-2 rounded-lg border border-green-800/40 bg-green-900/20 px-4 py-3 text-sm text-green-300">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Shadow concluído com bom desempenho. Política pronta para aprovação.
        </div>
      )}

      {run.started_at && (
        <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
          <Clock className="h-3 w-3" />
          Início: {fmtDate(run.started_at)}
          {run.completed_at && <> · Fim: {fmtDate(run.completed_at)}</>}
        </div>
      )}
    </div>
  );
}

// ── CandidateCard (Business + Technical view) ─────────────────────────────

function CandidateCard({
  candidate,
  onAction,
}: {
  candidate: CandidateDetail;
  onAction: (action: "ready" | "shadow" | "approve" | "reject") => void;
}) {
  const [showTechnical, setShowTechnical] = useState(false);

  const canReady = candidate.status === "draft";
  const canShadow = candidate.status === "ready_for_shadow";
  const canApprove = candidate.status === "shadow_completed";
  const canReject = candidate.status === "shadow_completed" || candidate.status === "under_review";

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={candidate.status} />
            <TypeBadge type={candidate.type} />
            {candidate.template_id && (
              <span className="font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-text-muted)]/70">
                {candidate.template_id}
              </span>
            )}
          </div>
          <h2 className="mt-2 font-[family-name:var(--font-heading)] text-xl font-bold text-[var(--color-text)]">
            {candidate.title}
          </h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
            Criado em {fmtDate(candidate.created_at)} · Atualizado {fmtDate(candidate.updated_at)}
          </p>
        </div>

        {/* Action buttons */}
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {canReady && (
            <button
              onClick={() => onAction("ready")}
              className="flex items-center gap-2 rounded-lg border border-blue-800/40 bg-blue-900/10 px-4 py-2 text-sm font-semibold text-blue-400 transition-colors hover:bg-blue-900/25 cursor-pointer"
            >
              <PlayCircle className="h-4 w-4" />
              Marcar como pronto
            </button>
          )}
          {canShadow && (
            <button
              onClick={() => onAction("shadow")}
              className="flex items-center gap-2 rounded-lg bg-violet-700 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-violet-600 cursor-pointer"
            >
              <FlaskConical className="h-4 w-4" />
              Executar Shadow
            </button>
          )}
          {canApprove && (
            <button
              onClick={() => onAction("approve")}
              className="flex items-center gap-2 rounded-lg bg-green-700 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-green-600 cursor-pointer"
            >
              <CheckCircle2 className="h-4 w-4" />
              Aprovar
            </button>
          )}
          {canReject && (
            <button
              onClick={() => onAction("reject")}
              className="flex items-center gap-2 rounded-lg border border-red-800/40 bg-red-900/10 px-4 py-2 text-sm font-semibold text-red-400 transition-colors hover:bg-red-900/25 cursor-pointer"
            >
              <XCircle className="h-4 w-4" />
              Rejeitar
            </button>
          )}
        </div>
      </div>

      {/* Business view (always visible) */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          Visão de negócio
        </p>
        <p className="text-sm leading-relaxed text-[var(--color-text)]">{candidate.business_summary}</p>
      </div>

      {/* Technical view (expandable) */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <button
          onClick={() => setShowTechnical((v) => !v)}
          className="flex w-full items-center justify-between px-5 py-4 text-left cursor-pointer hover:bg-white/5 rounded-xl transition-colors"
        >
          <span className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
            Visão técnica
          </span>
          {showTechnical ? <ChevronDown className="h-4 w-4 text-[var(--color-text-muted)]" /> : <ChevronRight className="h-4 w-4 text-[var(--color-text-muted)]" />}
        </button>
        {showTechnical && (
          <div className="border-t border-[var(--color-border)] px-5 py-4">
            <p className="font-[family-name:var(--font-mono)] text-xs leading-relaxed text-[var(--color-text-muted)]">
              {candidate.technical_summary}
            </p>
            {candidate.trigger_conditions.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-xs font-medium text-[var(--color-text-muted)]">Condições de trigger</p>
                <div className="space-y-1">
                  {candidate.trigger_conditions.map((tc, i) => (
                    <div key={`${tc.field}-${tc.operator}-${i}`} className="flex items-center gap-2 rounded bg-white/5 px-3 py-1.5">
                      <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--color-primary)]">{tc.field}</span>
                      <span className="text-xs text-[var(--color-text-muted)]">{tc.operator}</span>
                      <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--color-text)]">{fmtTriggerValue(tc.value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Shadow result */}
      {candidate.shadow_run && (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <ShadowResult run={candidate.shadow_run} />
        </div>
      )}

      {/* Lifecycle timeline */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
        <p className="mb-4 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          Histórico de lifecycle
        </p>
        <LifecycleTimeline events={candidate.lifecycle_events} />
      </div>
    </div>
  );
}

// ── Template selector ──────────────────────────────────────────────────────

function TemplateSelector({
  templates,
  onSelect,
  loading,
  error,
}: {
  templates: PolicyTemplate[];
  onSelect: (templateId: string) => void;
  loading: boolean;
  error: string | null;
}) {
  const TYPE_COLORS: Record<string, string> = {
    bypass: "text-violet-400",
    guardrail: "text-red-400",
    route_to_api: "text-blue-400",
    handoff: "text-amber-400",
  };

  return (
    <div className="space-y-3">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-800/40 bg-red-950/30 px-4 py-2.5 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {templates.map((tpl) => (
          <button
            key={tpl.id}
            onClick={() => onSelect(tpl.id)}
            disabled={loading}
            className="group relative flex flex-col rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-left transition-all hover:border-[var(--color-primary)]/50 hover:bg-white/5 cursor-pointer disabled:opacity-50"
          >
            <div className="flex items-center justify-between">
              <TypeBadge type={tpl.type} />
              <span className="text-[10px] text-[var(--color-text-muted)]">{tpl.vertical}</span>
            </div>
            <p className={`mt-3 text-sm font-semibold ${TYPE_COLORS[tpl.type] ?? "text-[var(--color-text)]"}`}>
              {tpl.title}
            </p>
            {tpl.description && (
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">{tpl.description}</p>
            )}
            <div className="mt-3 flex items-center gap-1 text-xs text-[var(--color-primary)] opacity-0 transition-opacity group-hover:opacity-100">
              <Plus className="h-3 w-3" />
              Instanciar
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Candidate list row ─────────────────────────────────────────────────────

function CandidateRow({
  candidate,
  onClick,
}: {
  candidate: PolicyCandidate;
  onClick: () => void;
}) {
  return (
    <tr
      onClick={onClick}
      className="cursor-pointer border-b border-[var(--color-border)]/50 transition-colors hover:bg-white/5"
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <TypeBadge type={candidate.type} />
          <span className="text-sm font-medium text-[var(--color-text)]">{candidate.title}</span>
        </div>
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={candidate.status} />
      </td>
      <td className="px-4 py-3 text-xs text-[var(--color-text-muted)]">
        {fmtDate(candidate.updated_at)}
      </td>
      <td className="px-4 py-3 text-right">
        <ChevronRight className="ml-auto h-4 w-4 text-[var(--color-text-muted)]" />
      </td>
    </tr>
  );
}

// ── GovernancePage ─────────────────────────────────────────────────────────

type ActionType = "ready" | "shadow" | "approve" | "reject" | null;

export function GovernancePage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<PolicyCandidate | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [actionType, setActionType] = useState<ActionType>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // ── Candidates list ───────────────────────────────────────────────────
  const {
    data: candidates,
    isDemo: candidatesDemo,
    refetch: refetchCandidates,
  } = useApiData(
    getKairosCandidates,
    MOCK_CANDIDATES,
    { treatEmptyAsDemo: (d) => d.length === 0 },
  );

  // ── Templates ─────────────────────────────────────────────────────────
  const {
    data: templates,
  } = useApiData(getKairosTemplates, MOCK_TEMPLATES);

  // ── Candidate detail — polls every 30s when shadow is running ─────────
  const detailFetcher = useCallback(
    () => (selectedId ? getKairosCandidate(selectedId) : Promise.resolve(null as unknown as CandidateDetail)),
    [selectedId],
  );
  // isRunning is derived from the live polled detail (not stale selectedCandidate)
  // so polling stops as soon as the sweep transitions shadow_running → shadow_completed.
  const [isRunning, setIsRunning] = useState(false);
  const {
    data: detail,
    isDemo: detailDemo,
    refetch: refetchDetail,
  } = useApiData(
    detailFetcher,
    selectedCandidate ? buildMockDetail(selectedCandidate) : buildMockDetail(MOCK_CANDIDATES[0]),
    { enabled: !!selectedId, intervalMs: isRunning ? 30_000 : undefined },
  );
  // Sync isRunning from live detail so polling halts when sweep completes the run.
  useEffect(() => {
    setIsRunning(detail?.status === "shadow_running");
  }, [detail?.status]);

  // ── Handlers ──────────────────────────────────────────────────────────
  const handleSelectCandidate = (candidate: PolicyCandidate) => {
    setSelectedId(candidate.id);
    setSelectedCandidate(candidate);
    setShowTemplates(false);
  };

  const handleBack = () => {
    setSelectedId(null);
    setSelectedCandidate(null);
    setActionType(null);
    setActionError(null);
  };

  const handleAction = (action: ActionType) => {
    setActionType(action);
    setActionError(null);
  };

  const handleConfirm = async (reason: string) => {
    if (!selectedId || !actionType) return;
    setActionLoading(true);
    setActionError(null);
    try {
      let updated: PolicyCandidate | undefined;
      if (actionType === "ready") {
        updated = await markCandidateReady(selectedId);
      } else if (actionType === "shadow") {
        updated = await startKairosShadow(selectedId);
      } else if (actionType === "approve") {
        updated = await approveKairosCandidate(selectedId, reason);
      } else if (actionType === "reject") {
        updated = await rejectKairosCandidate(selectedId, reason);
      }
      if (updated) setSelectedCandidate(updated);
      setActionType(null);
      refetchDetail();
      refetchCandidates();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Erro na operação");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateFromTemplate = async (templateId: string) => {
    setCreateLoading(true);
    setCreateError(null);
    try {
      const candidate = await createCandidateFromTemplate(templateId);
      refetchCandidates();
      setShowTemplates(false);
      handleSelectCandidate(candidate);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Erro ao instanciar template. Verifique o backend.");
    } finally {
      setCreateLoading(false);
    }
  };

  // "ready" action doesn't need a reason — short-circuit to confirm immediately
  const actionModalConfig: Record<NonNullable<ActionType>, {
    title: string;
    description: string;
    impact: string[];
    severity: "warning" | "critical";
    actionLabel: string;
    needsReason: boolean;
  }> = {
    ready: {
      title: "Marcar como pronto para Shadow?",
      description: "A política será movida para ready_for_shadow e poderá iniciar observação.",
      impact: [
        "• A política ainda não afeta o pipeline de decisão",
        "• Um operador deverá iniciar o Shadow Run manualmente",
        "• Esta ação pode ser revertida via revisão (under_review)",
      ],
      severity: "warning",
      actionLabel: "Confirmar",
      needsReason: false,
    },
    shadow: {
      title: "Executar Shadow Run?",
      description: "A política será observada em tráfego real por no mínimo 500 observações ou 7 dias.",
      impact: [
        "• A política NÃO afetará decisões do pipeline durante o shadow",
        "• Contadores de match/fallback serão registrados silenciosamente",
        "• O sweep finalizará o shadow automaticamente ao atingir os critérios",
      ],
      severity: "warning",
      actionLabel: "Confirmar shadow",
      needsReason: false,
    },
    approve: {
      title: "Aprovar para produção?",
      description: "A política será ativada no pipeline de decisão e afetará tráfego real imediatamente.",
      impact: [
        "• A política entrará em vigor no próximo request do tenant",
        "• O impacto projetado é baseado nos dados do shadow run",
        "• Um operador poderá deprecar a política a qualquer momento",
      ],
      severity: "warning",
      actionLabel: "Confirmar aprovação",
      needsReason: true,
    },
    reject: {
      title: "Rejeitar política?",
      description: "A política será marcada como rejeitada e poderá ser arquivada.",
      impact: [
        "• A política não será ativada em produção",
        "• O motivo de rejeição ficará registrado no audit log",
        "• Dados do shadow run serão preservados para análise futura",
      ],
      severity: "critical",
      actionLabel: "Confirmar rejeição",
      needsReason: true,
    },
  };

  const activeConfig = actionType ? actionModalConfig[actionType] : null;

  // ── Render: Detail view ───────────────────────────────────────────────
  if (selectedId) {
    return (
      <div className="space-y-6">
        <div>
          <button
            onClick={handleBack}
            className="mb-3 flex items-center gap-2 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors cursor-pointer"
          >
            <ArrowLeft className="h-4 w-4" />
            Voltar para candidatos
          </button>
          {detailDemo && <DemoBanner onRetry={refetchDetail} />}
        </div>

        <CandidateCard
          candidate={detail}
          onAction={handleAction}
        />

        {activeConfig && (
          <ConfirmActionModal
            open={!!actionType}
            severity={activeConfig.severity}
            title={activeConfig.title}
            description={activeConfig.description}
            impact={activeConfig.impact}
            actionLabel={activeConfig.actionLabel}
            loading={actionLoading}
            error={actionError}
            onConfirm={handleConfirm}
            onCancel={() => { setActionType(null); setActionError(null); }}
          />
        )}
      </div>
    );
  }

  // ── Render: List view ─────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            Governança de Políticas
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Ciclo de vida de PolicyCandidates — shadow, aprovação e auditoria
          </p>
        </div>
        <button
          onClick={() => { setShowTemplates((v) => !v); setCreateError(null); }}
          className="flex items-center gap-2 rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-semibold text-white transition-colors hover:opacity-90 cursor-pointer"
        >
          <Plus className="h-4 w-4" />
          Nova política
        </button>
      </div>

      {candidatesDemo && <DemoBanner onRetry={refetchCandidates} />}

      {/* Template picker */}
      {showTemplates && (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm font-semibold text-[var(--color-text)]">
              Escolha um template para instanciar
            </p>
            <button
              onClick={() => { setShowTemplates(false); setCreateError(null); }}
              className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] cursor-pointer"
            >
              Cancelar
            </button>
          </div>
          <TemplateSelector
            templates={templates}
            onSelect={handleCreateFromTemplate}
            loading={createLoading}
            error={createError}
          />
        </div>
      )}

      {/* Candidates table */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="flex items-center gap-3 border-b border-[var(--color-border)] px-5 py-4">
          <Scale className="h-4 w-4 text-[var(--color-text-muted)]" />
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-text)]">Candidatos</h2>
            <p className="text-xs text-[var(--color-text-muted)]">
              {candidates.length} {candidates.length === 1 ? "política" : "políticas"} · clique para ver detalhes
            </p>
          </div>
        </div>

        {candidates.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <Scale className="mx-auto mb-3 h-8 w-8 text-[var(--color-text-muted)]/40" />
            <p className="text-sm text-[var(--color-text-muted)]">
              Nenhum candidato ainda. Clique em "Nova política" para instanciar um template.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)]">
                  {["Política", "Status", "Atualizado em", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-medium text-[var(--color-text-muted)]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <CandidateRow
                    key={c.id}
                    candidate={c}
                    onClick={() => handleSelectCandidate(c)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
