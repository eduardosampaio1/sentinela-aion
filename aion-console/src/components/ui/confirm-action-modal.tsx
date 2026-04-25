"use client";

/**
 * ConfirmActionModal — Enterprise-grade confirmation gate for dangerous mutations.
 *
 * Forces the actor to:
 *   1. Read the impact of the action
 *   2. Confirm their current role
 *   3. Provide a written justification (sent as X-Aion-Actor-Reason header)
 *
 * The reason is mandatory — the backend rejects the operation without it.
 * Every confirmation is recorded in the audit trail with the actor's identity.
 */
import { useState, useEffect, useRef } from "react";
import { AlertTriangle, ShieldAlert, User } from "lucide-react";
import { useRole } from "@/hooks/use-role";
import { ROLE_LABELS, ROLE_COLORS } from "@/lib/permissions";

export type ActionSeverity = "warning" | "critical";

export interface ConfirmActionProps {
  /** Whether the modal is visible. */
  open: boolean;
  /** Short title — what action the user is about to take. */
  title: string;
  /** One sentence describing what will happen. */
  description: string;
  /** Bullet list of specific consequences. */
  impact: string[];
  /** "warning" = amber (promote, toggle, budget). "critical" = red (killswitch, LGPD, rollback). */
  severity?: ActionSeverity;
  /** Label for the confirm button. Defaults to "Confirmar". */
  actionLabel?: string;
  /** External loading state (e.g. while awaiting the API). */
  loading?: boolean;
  /** API error message to display inside the modal. */
  error?: string | null;
  /** Called with the typed reason when user confirms. */
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

const MIN_REASON_LENGTH = 10;

export function ConfirmActionModal({
  open,
  title,
  description,
  impact,
  severity = "warning",
  actionLabel = "Confirmar",
  loading = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmActionProps) {
  const [reason, setReason] = useState("");
  const { role } = useRole();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Reset reason when modal opens
  useEffect(() => {
    if (open) {
      setReason("");
      // Focus textarea after animation frame
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
  }, [open]);

  if (!open) return null;

  const isCritical = severity === "critical";
  const reasonValid = reason.trim().length >= MIN_REASON_LENGTH;

  function handleConfirm() {
    if (!reasonValid || loading) return;
    onConfirm(reason.trim());
  }

  function handleBackdropClick(e: React.MouseEvent) {
    if (e.target === e.currentTarget) onCancel();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") onCancel();
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && reasonValid) handleConfirm();
  }

  const borderColor = isCritical ? "border-red-800/60" : "border-amber-800/40";
  const headerBg = isCritical ? "border-red-800/40 bg-red-950/30" : "border-amber-800/30 bg-amber-950/20";
  const impactBg = isCritical ? "border-red-800/40 bg-red-950/20" : "border-amber-800/30 bg-amber-950/10";
  const impactText = isCritical ? "text-red-300" : "text-amber-300";
  const Icon = isCritical ? ShieldAlert : AlertTriangle;
  const iconColor = isCritical ? "text-red-400" : "text-amber-400";
  const titleColor = isCritical ? "text-red-300" : "text-amber-300";
  const confirmBg = isCritical
    ? "bg-red-700 hover:bg-red-600 disabled:bg-red-900"
    : "bg-amber-700 hover:bg-amber-600 disabled:bg-amber-900";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleBackdropClick}
      onKeyDown={handleKeyDown}
      tabIndex={-1}
    >
      <div
        className={`w-full max-w-lg rounded-2xl border bg-[var(--color-surface)] shadow-2xl ${borderColor}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className={`flex items-start gap-3 rounded-t-2xl border-b px-6 py-5 ${headerBg}`}>
          <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${iconColor}`} aria-hidden="true" />
          <div className="flex-1 min-w-0">
            <h3
              id="confirm-modal-title"
              className={`text-base font-semibold ${titleColor}`}
            >
              {title}
            </h3>
            <p className="mt-1 text-sm text-[var(--color-text-muted)]">{description}</p>
          </div>
        </div>

        <div className="space-y-5 px-6 py-5">
          {/* ── Actor role ── */}
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <User className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>Executando como:</span>
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${ROLE_COLORS[role]}`}>
              {ROLE_LABELS[role]}
            </span>
          </div>

          {/* ── Impact bullets ── */}
          {impact.length > 0 && (
            <div className={`rounded-lg border p-4 space-y-1.5 text-sm ${impactBg}`}>
              {impact.map((line, i) => (
                <p key={i} className={impactText}>
                  {line}
                </p>
              ))}
            </div>
          )}

          {/* ── Reason field ── */}
          <div className="space-y-1.5">
            <label
              htmlFor="confirm-action-reason"
              className="block text-xs font-medium text-[var(--color-text-muted)]"
            >
              Motivo da mudança{" "}
              <span className="opacity-60">(mín. {MIN_REASON_LENGTH} caracteres — obrigatório)</span>
            </label>
            <textarea
              id="confirm-action-reason"
              ref={textareaRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Descreva o motivo desta ação para o audit log..."
              disabled={loading}
              className="w-full resize-none rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]/40 focus:border-[var(--color-primary)]/60 focus:outline-none transition-colors disabled:opacity-50"
            />
            {reason.trim().length > 0 && reason.trim().length < MIN_REASON_LENGTH && (
              <p className="text-[10px] text-amber-400">
                {reason.trim().length}/{MIN_REASON_LENGTH} caracteres mínimos
              </p>
            )}
          </div>

          {/* ── API error ── */}
          {error && (
            <div className="rounded-lg border border-red-800/40 bg-red-950/50 px-3 py-2 text-xs text-red-400">
              {error}
            </div>
          )}

          {/* ── Compliance footer ── */}
          <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]/60">
            Esta ação será registrada no audit log e poderá afetar tráfego em produção.
            Assegure-se de ter autorização explícita antes de confirmar.
          </p>
        </div>

        {/* ── Actions ── */}
        <div className="flex justify-end gap-3 rounded-b-2xl border-t border-[var(--color-border)] px-6 py-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="cursor-pointer rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)] disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!reasonValid || loading}
            className={`cursor-pointer rounded-lg px-4 py-2 text-sm font-semibold text-white transition-all disabled:cursor-not-allowed disabled:opacity-40 ${confirmBg}`}
          >
            {loading ? "Aguarde…" : actionLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
