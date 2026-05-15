"use client";

import { useState, useEffect } from "react";
import {
  Network,
  ShieldCheck,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  ArrowRight,
  Zap,
  TrendingDown,
  Clock,
  AlertOctagon,
  Info,
} from "lucide-react";
import { DemoBanner } from "@/components/ui/demo-banner";
import { ConfirmActionModal } from "@/components/ui/confirm-action-modal";
import { useApiData } from "@/lib/use-api-data";
import {
  browseCollectivePolicies,
  getInstalledPolicies,
  installCollectivePolicy,
  promoteCollectivePolicy,
} from "@/lib/api";
import { getHealth, type HealthInfo } from "@/lib/api/observability";
import { useT } from "@/lib/i18n";
import {
  mockCollectivePolicies,
  mockInstalledPolicies,
} from "@/lib/mock-data";
import type { CollectivePolicy, InstalledCollectivePolicy } from "@/lib/types";

// ─── Sector filter config ──────────────────────────────────────────────────────

const SECTOR_TABS = [
  { id: "all", label: "Todos" },
  { id: "banking", label: "Banking" },
  { id: "fintech", label: "Fintech" },
  { id: "telecom", label: "Telecom" },
  { id: "healthcare", label: "Healthcare" },
  { id: "general", label: "Geral" },
] as const;

type SectorTab = (typeof SECTOR_TABS)[number]["id"];

const SECTOR_COLORS: Record<string, string> = {
  banking: "bg-sky-900/30 text-sky-400 border-sky-800/50",
  fintech: "bg-violet-900/30 text-violet-400 border-violet-800/50",
  telecom: "bg-amber-900/30 text-amber-400 border-amber-800/50",
  healthcare: "bg-teal-900/30 text-teal-400 border-teal-800/50",
  insurance: "bg-indigo-900/30 text-indigo-400 border-indigo-800/50",
  general: "bg-slate-800/60 text-slate-400 border-slate-700/50",
};

const STATUS_COLORS: Record<string, string> = {
  sandbox:
    "bg-amber-900/20 border-amber-800/40 text-amber-400",
  shadow:
    "bg-sky-900/20 border-sky-800/40 text-sky-400",
  production:
    "bg-emerald-900/20 border-emerald-800/40 text-emerald-400",
};

const STATUS_LABELS: Record<string, string> = {
  sandbox: "Sandbox",
  shadow: "Shadow",
  production: "Produção",
};

// ─── Metric helpers ────────────────────────────────────────────────────────────

function fmtLatency(ms: number): string {
  if (ms === 0) return "0ms";
  const sign = ms < 0 ? "−" : "+";
  return `${sign}${Math.abs(ms).toFixed(0)}ms`;
}

function fmtSavings(pct: number): string {
  if (pct <= 0) return "";
  return `+${pct.toFixed(0)}% savings`;
}

function FpBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100 * 10) / 10;
  const color =
    pct < 1 ? "bg-emerald-500" : pct < 3 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-white/10">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${Math.min(pct * 10, 100)}%` }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-[var(--color-text-muted)]">
        {pct}% FP
      </span>
    </div>
  );
}

// ─── Provenance accordion ──────────────────────────────────────────────────────

function ProvenanceAccordion({ policy }: { policy: CollectivePolicy }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-t border-[var(--color-border)]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
      >
        <span className="font-medium">Provenance</span>
        {open ? (
          <ChevronUp className="h-3.5 w-3.5" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" />
        )}
      </button>
      {open && (
        <div className="space-y-3 border-t border-[var(--color-border)] bg-white/[0.02] px-4 py-3">
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="text-[var(--color-text-muted)]">
              v{policy.provenance.version}
            </span>
            <span className="text-[var(--color-text-muted)]">
              atualizado em{" "}
              {new Date(policy.provenance.last_updated).toLocaleDateString(
                "pt-BR",
                { day: "2-digit", month: "short", year: "numeric" },
              )}
            </span>
            {policy.provenance.signed_by_aion && (
              <span className="flex items-center gap-1 rounded-full border border-teal-800/40 bg-teal-900/20 px-2 py-0.5 text-[10px] font-medium text-teal-400">
                <CheckCircle2 className="h-2.5 w-2.5" />
                Assinado AION
              </span>
            )}
          </div>
          {policy.provenance.changelog.length > 0 && (
            <ul className="space-y-1">
              {policy.provenance.changelog.map((entry, i) => (
                <li
                  key={i}
                  className="text-[10px] text-[var(--color-text-muted)] font-[family-name:var(--font-mono)]"
                >
                  · {entry}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Policy card ───────────────────────────────────────────────────────────────

interface PolicyCardProps {
  policy: CollectivePolicy;
  installedStatus?: InstalledCollectivePolicy;
  onInstall: (policy: CollectivePolicy) => void;
}

function PolicyCard({ policy, installedStatus, onInstall }: PolicyCardProps) {
  const confidence = Math.round(policy.metrics.confidence_score * 100);
  const installed = installedStatus;

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] transition-colors hover:border-white/20">
      <div className="flex-1 p-5 space-y-4">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">
                {policy.name}
              </h3>
              {policy.editorial && (
                <span className="flex items-center gap-1 rounded-full border border-yellow-700/50 bg-yellow-900/20 px-2 py-0.5 text-[10px] font-semibold text-yellow-400">
                  <ShieldCheck className="h-2.5 w-2.5" />
                  AION Editorial
                </span>
              )}
            </div>
            {/* Sector badges */}
            <div className="flex flex-wrap gap-1.5">
              {policy.sectors.map((sector) => (
                <span
                  key={sector}
                  className={`rounded-full border px-2 py-0.5 text-[10px] font-medium capitalize ${
                    SECTOR_COLORS[sector] ?? SECTOR_COLORS.general
                  }`}
                >
                  {sector}
                </span>
              ))}
            </div>
          </div>
          {/* Confidence badge */}
          <div className="flex-shrink-0 text-right">
            <div className="text-lg font-bold text-[var(--color-text)]">
              {confidence}%
            </div>
            <div className="text-[10px] text-[var(--color-text-muted)]">
              confiança
            </div>
          </div>
        </div>

        <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
          {policy.description}
        </p>

        {/* Metrics row */}
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
            <Network className="h-3 w-3 shrink-0" />
            <span>
              <span className="font-medium text-[var(--color-text)]">
                {policy.metrics.installs_production}
              </span>{" "}
              em produção
            </span>
          </div>
          {policy.metrics.avg_savings_pct > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-emerald-400">
              <TrendingDown className="h-3 w-3 shrink-0" />
              <span className="font-medium">{fmtSavings(policy.metrics.avg_savings_pct)}</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
            <Clock className="h-3 w-3 shrink-0" />
            <span className="font-medium tabular-nums">
              {fmtLatency(policy.metrics.avg_latency_change_ms)}
            </span>
          </div>
        </div>

        {/* FP rate bar */}
        <FpBar rate={policy.metrics.false_positive_rate} />

        {/* Install state or button */}
        {installed ? (
          <div
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium ${STATUS_COLORS[installed.status]}`}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            Instalado — {STATUS_LABELS[installed.status]}
          </div>
        ) : (
          <button
            onClick={() => onInstall(policy)}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-[var(--color-primary)]/30 bg-[var(--color-primary)]/10 px-3 py-2 text-xs font-medium text-[var(--color-primary)] transition-colors hover:bg-[var(--color-primary)]/20"
          >
            <Zap className="h-3.5 w-3.5" />
            Instalar em Sandbox
          </button>
        )}
      </div>

      {/* Provenance accordion */}
      <ProvenanceAccordion policy={policy} />
    </div>
  );
}

// ─── Installed policies table ──────────────────────────────────────────────────

function InstalledTable({
  installed,
  policies,
  onPromote,
}: {
  installed: InstalledCollectivePolicy[];
  policies: CollectivePolicy[];
  onPromote: (item: InstalledCollectivePolicy) => void;
}) {
  const policyMap = new Map(policies.map((p) => [p.id, p]));

  return (
    <div className="space-y-3">
      <h2 className="font-[family-name:var(--font-heading)] text-base font-semibold text-[var(--color-text)]">
        Políticas Instaladas
      </h2>
      <div className="overflow-hidden rounded-xl border border-[var(--color-border)]">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-white/[0.02] text-[var(--color-text-muted)]">
              <th className="px-4 py-3 text-left font-medium">Política</th>
              <th className="px-4 py-3 text-left font-medium">Versão</th>
              <th className="px-4 py-3 text-left font-medium">Status</th>
              <th className="px-4 py-3 text-left font-medium">Instalado em</th>
              <th className="px-4 py-3 text-right font-medium">Ações</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-border)]">
            {installed.map((item) => {
              const policy = policyMap.get(item.policy_id);
              const canPromote = item.status !== "production";
              return (
                <tr
                  key={item.policy_id}
                  className="bg-[var(--color-surface)] transition-colors hover:bg-white/[0.02]"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-[var(--color-text)]">
                      {policy?.name ?? item.policy_id}
                    </div>
                    <div className="text-[10px] text-[var(--color-text-muted)]">
                      {item.policy_id}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-[family-name:var(--font-mono)] text-[var(--color-text-muted)]">
                    v{item.version}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full border px-2.5 py-0.5 text-[10px] font-semibold ${STATUS_COLORS[item.status]}`}
                    >
                      {STATUS_LABELS[item.status]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[var(--color-text-muted)]">
                    {new Date(item.installed_at * 1000).toLocaleDateString(
                      "pt-BR",
                      { day: "2-digit", month: "short" },
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {canPromote && (
                      <button
                        onClick={() => onPromote(item)}
                        className="flex items-center gap-1 rounded border border-[var(--color-primary)]/30 bg-[var(--color-primary)]/10 px-2.5 py-1 text-[10px] font-medium text-[var(--color-primary)] transition-colors hover:bg-[var(--color-primary)]/20"
                      >
                        Promover
                        <ArrowRight className="h-3 w-3" />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export function CollectivePage() {
  const t = useT();
  const [activeSector, setActiveSector] = useState<SectorTab>("all");
  const [installTarget, setInstallTarget] = useState<CollectivePolicy | null>(null);
  const [promoteTarget, setPromoteTarget] = useState<InstalledCollectivePolicy | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [healthInfo, setHealthInfo] = useState<HealthInfo | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealthInfo)
      .catch(() => setHealthInfo(null));
  }, []);

  const isPocDecision = healthInfo?.aion_mode === "poc_decision";

  // ── Data fetching ──────────────────────────────────────────────────────────
  const sectorParam = activeSector !== "all" ? activeSector : undefined;

  const {
    data: policies,
    isDemo,
    refetch: refetchPolicies,
  } = useApiData(
    () => browseCollectivePolicies(sectorParam),
    activeSector === "all"
      ? mockCollectivePolicies
      : mockCollectivePolicies.filter((p) =>
          p.sectors.includes(activeSector),
        ),
  );

  const {
    data: installed,
    refetch: refetchInstalled,
  } = useApiData(
    () => getInstalledPolicies(),
    mockInstalledPolicies,
  );

  // Build a map for O(1) lookup in table
  const installedMap = new Map(installed.map((i) => [i.policy_id, i]));

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleInstall = async (reason: string) => {
    if (!installTarget) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await installCollectivePolicy(installTarget.id, reason);
      setInstallTarget(null);
      void refetchInstalled();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Erro ao instalar — tente novamente",
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handlePromote = async (reason: string) => {
    if (!promoteTarget) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await promoteCollectivePolicy(promoteTarget.policy_id, reason);
      setPromoteTarget(null);
      void refetchInstalled();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Erro ao promover — tente novamente",
      );
    } finally {
      setActionLoading(false);
    }
  };

  // ── Status helpers for promote modal ─────────────────────────────────────

  const promoteNextStatus = (current: string) => {
    if (current === "sandbox") return "Shadow Mode";
    if (current === "shadow") return "Produção";
    return "Produção";
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            {t("collective.title")}
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            {t("collective.subtitle")}
          </p>
        </div>
        <button
          onClick={() => {
            void refetchPolicies();
            void refetchInstalled();
          }}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Atualizar
        </button>
      </div>

      {isPocDecision && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-800/40 bg-amber-900/10 px-5 py-4">
          <Info className="h-4 w-4 flex-shrink-0 mt-0.5 text-amber-400" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-amber-400">
              Catálogo editorial — modo POC Decision-Only
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
              Neste modo, políticas instaladas <strong className="text-[var(--color-text)]">não são aplicadas no runtime</strong>.
              O ciclo de vida (Sandbox → Shadow → Produção) é rastreado administrativamente para demonstração.
              Runtime enforcement entra em Shadow Mode.
            </p>
          </div>
        </div>
      )}

      {isDemo && <DemoBanner onRetry={refetchPolicies} />}

      {/* Sector filter tabs */}
      <div className="flex flex-wrap gap-2">
        {SECTOR_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSector(tab.id)}
            className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
              activeSector === tab.id
                ? "border-[var(--color-primary)] bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
        <span className="ml-auto self-center text-xs text-[var(--color-text-muted)]">
          {policies.length} política{policies.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Policy grid */}
      {policies.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-20">
          <Network className="mb-3 h-10 w-10 text-[var(--color-text-muted)] opacity-40" />
          <p className="text-sm font-medium text-[var(--color-text)]">
            Nenhuma política para este setor
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            Selecione outro filtro acima
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {policies.map((policy) => (
            <PolicyCard
              key={policy.id}
              policy={policy}
              installedStatus={installedMap.get(policy.id)}
              onInstall={setInstallTarget}
            />
          ))}
        </div>
      )}

      {/* Installed table — only shown when there are installs */}
      {installed.length > 0 && (
        <InstalledTable
          installed={installed}
          policies={policies}
          onPromote={setPromoteTarget}
        />
      )}

      {/* Shadow Mode info banner */}
      <div className="flex items-start gap-3 rounded-xl border border-[var(--color-border)] bg-sky-900/10 px-5 py-4">
        <AlertOctagon className="h-4 w-4 flex-shrink-0 mt-0.5 text-sky-400" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-sky-400">
            Ciclo de vida: Sandbox → Shadow → Produção
          </p>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
            O status de cada política é rastreado administrativamente. A integração de
            runtime (aplicação automática no pipeline) está prevista para uma fase futura.
          </p>
        </div>
        <a
          href="/shadow"
          className="flex-shrink-0 flex items-center gap-1 rounded-lg border border-sky-800/40 px-3 py-1.5 text-xs font-medium text-sky-400 transition-colors hover:bg-sky-900/20"
        >
          Ver Shadow
          <ArrowRight className="h-3 w-3" />
        </a>
      </div>

      {/* Install confirmation modal */}
      <ConfirmActionModal
        open={installTarget !== null}
        title={`Instalar "${installTarget?.name ?? ""}"`}
        description="A política será instalada em ambiente Sandbox para avaliação de impacto. Nenhum tráfego de produção é afetado."
        impact={[
          `Política: ${installTarget?.id ?? ""}`,
          `Setores: ${installTarget?.sectors.join(", ") ?? ""}`,
          "Status inicial: Sandbox — sem impacto em produção",
          "Reversível com um clique a qualquer momento",
        ]}
        severity="warning"
        actionLabel="Instalar em Sandbox"
        loading={actionLoading}
        error={actionError}
        onConfirm={(reason) => void handleInstall(reason)}
        onCancel={() => {
          setInstallTarget(null);
          setActionError(null);
        }}
      />

      {/* Promote confirmation modal */}
      <ConfirmActionModal
        open={promoteTarget !== null}
        title={`Promover para ${promoteTarget ? promoteNextStatus(promoteTarget.status) : ""}`}
        description={`A política avançará de ${promoteTarget?.status ?? ""} para o próximo nível. Revise o impacto antes de confirmar.`}
        impact={[
          `Política: ${promoteTarget?.policy_id ?? ""}`,
          `Origem: ${promoteTarget?.status ?? ""} → ${promoteTarget ? promoteNextStatus(promoteTarget.status) : ""}`,
          "Alteração de status administrativo — nenhum tráfego é afetado nesta fase",
          "Reversível com um clique a qualquer momento",
        ]}
        severity="warning"
        actionLabel="Promover"
        loading={actionLoading}
        error={actionError}
        onConfirm={(reason) => void handlePromote(reason)}
        onCancel={() => {
          setPromoteTarget(null);
          setActionError(null);
        }}
      />
    </div>
  );
}
