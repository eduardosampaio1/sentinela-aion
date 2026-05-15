"use client";

import { useState, useEffect } from "react";
import { useApiData } from "@/lib/use-api-data";
import {
  rotateKeys,
  getStats,
  getKillswitch,
  activateKillswitch,
  deactivateKillswitch,
} from "@/lib/api";
import { mockStats } from "@/lib/mock-data";
import { ConfirmActionModal } from "@/components/ui/confirm-action-modal";
import { useT } from "@/lib/i18n";
import {
  Copy,
  Check,
  RefreshCw,
  Eye,
  EyeOff,
  Bell,
  Mail,
  Webhook,
  Hash,
  Globe,
  Building2,
  Key,
  Zap,
  AlertTriangle,
  TrendingDown,
  Activity,
  CalendarDays,
  Power,
  ShieldAlert,
} from "lucide-react";

type Tab = "geral" | "notificacoes" | "api" | "controles";

interface ToggleProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}

function Toggle({ checked, onChange, disabled = false }: ToggleProps) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => !disabled && onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none ${
        disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"
      } ${checked ? "bg-[var(--color-primary)]" : "bg-white/15"}`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200 ${
          checked ? "translate-x-[18px]" : "translate-x-[3px]"
        }`}
      />
    </button>
  );
}

function CopyButton({ text, small = false }: { text: string; small?: boolean }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className={`flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] transition-colors hover:bg-white/5 cursor-pointer ${
        small ? "px-2 py-1 text-[10px]" : "px-2.5 py-1.5 text-xs"
      } ${copied ? "text-green-400 border-green-800/50" : "text-[var(--color-text-muted)]"}`}
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copiado" : "Copiar"}
    </button>
  );
}

const TABS: { id: Tab; label: string }[] = [
  { id: "geral", label: "Geral" },
  { id: "notificacoes", label: "Notificações" },
  { id: "api", label: "API" },
  { id: "controles", label: "Controles avançados" },
];

export function SettingsPage() {
  const t = useT();
  const [activeTab, setActiveTab] = useState<Tab>("geral");
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotated, setRotated] = useState(false);
  const [showRotateConfirm, setShowRotateConfirm] = useState(false);
  const [rotateConfirmError, setRotateConfirmError] = useState<string | null>(null);

  // ─── Kill switch (moved here from /estixe) ────────────────────────────────
  const [ksActive, setKsActive] = useState(false);
  const [ksReason, setKsReason] = useState<string | null>(null);
  const [ksExpires, setKsExpires] = useState<number | null>(null);
  const [ksLoading, setKsLoading] = useState(true);
  const [showKsActivateModal, setShowKsActivateModal] = useState(false);
  const [ksReasonInput, setKsReasonInput] = useState("");
  const [ksActivating, setKsActivating] = useState(false);
  const [ksDeactivating, setKsDeactivating] = useState(false);
  const [ksDeactivateError, setKsDeactivateError] = useState<string | null>(null);
  const [showKsDeactivateConfirm, setShowKsDeactivateConfirm] = useState(false);

  useEffect(() => {
    getKillswitch()
      .then((res) => {
        setKsActive(res.killswitch_active);
        setKsReason(res.reason ?? null);
        setKsExpires(res.expires_at ?? null);
      })
      .catch(() => {})
      .finally(() => setKsLoading(false));
  }, []);

  const handleActivateKs = async () => {
    if (!ksReasonInput.trim()) return;
    setKsActivating(true);
    try {
      const res = await activateKillswitch(ksReasonInput.trim());
      setKsActive(true);
      setKsReason(res.reason);
      setKsExpires(res.expires_at);
      setShowKsActivateModal(false);
      setKsReasonInput("");
    } catch {
      // silent — UI stays in modal, user can retry
    } finally {
      setKsActivating(false);
    }
  };

  const handleDeactivateKs = async (reason: string) => {
    setKsDeactivating(true);
    setKsDeactivateError(null);
    try {
      await deactivateKillswitch(reason);
      setKsActive(false);
      setKsReason(null);
      setKsExpires(null);
      setShowKsDeactivateConfirm(false);
    } catch (err) {
      setKsDeactivateError(err instanceof Error ? err.message : "Erro ao desativar Kill Switch");
    } finally {
      setKsDeactivating(false);
    }
  };

  // Notification toggles
  const [notifSecurity, setNotifSecurity] = useState(true);
  const [notifBudget, setNotifBudget] = useState(true);
  const [notifPerf, setNotifPerf] = useState(false);
  const [notifWeekly, setNotifWeekly] = useState(true);
  const [notifEmail, setNotifEmail] = useState(true);
  const [notifWebhook, setNotifWebhook] = useState(false);
  const [notifSlack, setNotifSlack] = useState(false);
  const [notifPagerDuty, setNotifPagerDuty] = useState(false);

  const apiKeyMasked = "sk-aion-••••••••••••••••••••••••••••";
  const apiKeyFull = apiKeyMasked; // API key is managed server-side — never expose in client
  const endpoint = process.env.NEXT_PUBLIC_AION_API_URL ?? "http://localhost:8080";

  // Live stats for the API tab usage grid
  const { data: stats } = useApiData(getStats, mockStats, { intervalMs: 60_000 });

  const handleRotateConfirm = async (reason: string) => {
    setRotating(true);
    setRotateConfirmError(null);
    try {
      await rotateKeys([], reason);
      setRotated(true);
      setShowRotateConfirm(false);
      setTimeout(() => setRotated(false), 3000);
    } catch (err) {
      setRotateConfirmError(err instanceof Error ? err.message : "Erro ao rotacionar chave");
    } finally {
      setRotating(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          {t("settings.title")}
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          {t("settings.subtitle")}
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--color-border)]">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px cursor-pointer ${
              activeTab === tab.id
                ? "border-[var(--color-primary)] text-[var(--color-primary)]"
                : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── TAB: Geral ─────────────────────────────────────── */}
      {activeTab === "geral" && (
        <div className="space-y-5">
          {/* Tenant info */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Building2 className="h-4 w-4 text-[var(--color-text-muted)]" />
              <h2 className="text-sm font-semibold text-[var(--color-text)]">Tenant</h2>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
                  Nome da organização
                </label>
                <input
                  type="text"
                  defaultValue="Banco do Futuro S.A."
                  className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-primary)]/60 transition-colors"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
                  Slug / identificador
                </label>
                <input
                  type="text"
                  defaultValue="banco-futuro"
                  className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-[var(--color-text-muted)] outline-none cursor-not-allowed opacity-60"
                  readOnly
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
                  Fuso horário
                </label>
                <div className="relative">
                  <Globe className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--color-text-muted)]" />
                  <select className="w-full appearance-none rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] pl-8 pr-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-primary)]/60 transition-colors cursor-pointer">
                    <option>America/Sao_Paulo (UTC-3)</option>
                    <option>America/New_York (UTC-5)</option>
                    <option>Europe/Lisbon (UTC+0)</option>
                    <option>UTC</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
                  Plano atual
                </label>
                <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2">
                  <span className="inline-flex items-center rounded-md bg-[var(--color-primary)]/10 px-2 py-0.5 text-xs font-semibold text-[var(--color-primary)]">
                    Enterprise
                  </span>
                  <span className="text-xs text-[var(--color-text-muted)]">
                    Renovação em 15/09/2026
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Endpoint */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Zap className="h-4 w-4 text-[var(--color-text-muted)]" />
              <h2 className="text-sm font-semibold text-[var(--color-text)]">Endpoint da API</h2>
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-[var(--color-text-muted)]">
                {endpoint}
              </code>
              <CopyButton text={endpoint} />
            </div>
            <p className="mt-2 text-xs text-[var(--color-text-muted)]/60">
              Use este endereço como base URL nas suas integrações.
            </p>
          </div>

          {/* Save button */}
          <div className="flex justify-end">
            <button className="rounded-lg bg-[var(--color-cta)] px-5 py-2 text-sm font-semibold text-white hover:opacity-90 transition-opacity cursor-pointer">
              Salvar alterações
            </button>
          </div>
        </div>
      )}

      {/* ── TAB: Notificações ───────────────────────────────── */}
      {activeTab === "notificacoes" && (
        <div className="space-y-5">
          {/* Alert types */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
            <div className="flex items-center gap-2 border-b border-[var(--color-border)] p-5">
              <Bell className="h-4 w-4 text-[var(--color-text-muted)]" />
              <h2 className="text-sm font-semibold text-[var(--color-text)]">Tipos de alerta</h2>
            </div>
            <div className="divide-y divide-[var(--color-border)]">
              {[
                {
                  icon: AlertTriangle,
                  label: "Alertas de segurança",
                  desc: "Bloqueios críticos, PIIs detectados, sessões de alto risco",
                  color: "text-red-400",
                  value: notifSecurity,
                  set: setNotifSecurity,
                },
                {
                  icon: TrendingDown,
                  label: "Alertas de economia",
                  desc: "Budget próximo do limite, downgrades automáticos",
                  color: "text-amber-400",
                  value: notifBudget,
                  set: setNotifBudget,
                },
                {
                  icon: Activity,
                  label: "Degradação de performance",
                  desc: "Latência P95 acima do threshold, erros no pipeline",
                  color: "text-blue-400",
                  value: notifPerf,
                  set: setNotifPerf,
                },
                {
                  icon: CalendarDays,
                  label: "Relatório semanal",
                  desc: "Resumo de uso, economia e decisões da semana",
                  color: "text-[var(--color-primary)]",
                  value: notifWeekly,
                  set: setNotifWeekly,
                },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.label}
                    className="flex items-center justify-between px-5 py-4"
                  >
                    <div className="flex items-center gap-3">
                      <Icon className={`h-4 w-4 ${item.color}`} />
                      <div>
                        <p className="text-sm font-medium text-[var(--color-text)]">
                          {item.label}
                        </p>
                        <p className="text-xs text-[var(--color-text-muted)]">{item.desc}</p>
                      </div>
                    </div>
                    <Toggle checked={item.value} onChange={item.set} />
                  </div>
                );
              })}
            </div>
          </div>

          {/* Delivery */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
            <div className="flex items-center gap-2 border-b border-[var(--color-border)] p-5">
              <Mail className="h-4 w-4 text-[var(--color-text-muted)]" />
              <h2 className="text-sm font-semibold text-[var(--color-text)]">Entrega</h2>
            </div>
            <div className="divide-y divide-[var(--color-border)]">
              <div className="flex items-center justify-between px-5 py-4">
                <div className="flex items-center gap-3">
                  <Mail className="h-4 w-4 text-[var(--color-text-muted)]" />
                  <div>
                    <p className="text-sm font-medium text-[var(--color-text)]">E-mail</p>
                    <p className="text-xs text-[var(--color-text-muted)]">
                      lordduardo@gmail.com
                    </p>
                  </div>
                </div>
                <Toggle checked={notifEmail} onChange={setNotifEmail} />
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <Webhook className="h-4 w-4 text-[var(--color-text-muted)]" />
                    <div>
                      <p className="text-sm font-medium text-[var(--color-text)]">Webhook</p>
                      <p className="text-xs text-[var(--color-text-muted)]">
                        POST para URL configurada
                      </p>
                    </div>
                  </div>
                  <Toggle checked={notifWebhook} onChange={setNotifWebhook} />
                </div>
                {notifWebhook && (
                  <input
                    type="url"
                    placeholder="https://hooks.empresa.com/aion-alerts"
                    className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-[var(--color-text)] placeholder-[var(--color-text-muted)]/40 outline-none focus:border-[var(--color-primary)]/60 transition-colors"
                  />
                )}
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <Hash className="h-4 w-4 text-[var(--color-text-muted)]" />
                    <div>
                      <p className="text-sm font-medium text-[var(--color-text)]">Slack</p>
                      <p className="text-xs text-[var(--color-text-muted)]">
                        Incoming webhook do canal de alertas
                      </p>
                    </div>
                  </div>
                  <Toggle checked={notifSlack} onChange={setNotifSlack} />
                </div>
                {notifSlack && (
                  <input
                    type="url"
                    placeholder="https://hooks.slack.com/services/T00/B00/xxx"
                    className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-[var(--color-text)] placeholder-[var(--color-text-muted)]/40 outline-none focus:border-[var(--color-primary)]/60 transition-colors"
                  />
                )}
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <Bell className="h-4 w-4 text-[var(--color-text-muted)]" />
                    <div>
                      <p className="text-sm font-medium text-[var(--color-text)]">PagerDuty</p>
                      <p className="text-xs text-[var(--color-text-muted)]">
                        Alertas críticos — provider indisponível, killswitch
                      </p>
                    </div>
                  </div>
                  <Toggle checked={notifPagerDuty} onChange={setNotifPagerDuty} />
                </div>
                {notifPagerDuty && (
                  <input
                    type="password"
                    placeholder="Integration key do PagerDuty"
                    autoComplete="off"
                    className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-[var(--color-text)] placeholder-[var(--color-text-muted)]/40 outline-none focus:border-[var(--color-primary)]/60 transition-colors"
                  />
                )}
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button className="rounded-lg bg-[var(--color-cta)] px-5 py-2 text-sm font-semibold text-white hover:opacity-90 transition-opacity cursor-pointer">
              Salvar preferências
            </button>
          </div>
        </div>
      )}

      {/* ── TAB: API ─────────────────────────────────────────── */}
      {activeTab === "api" && (
        <div className="space-y-5">
          {/* API Key */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Key className="h-4 w-4 text-[var(--color-text-muted)]" />
              <h2 className="text-sm font-semibold text-[var(--color-text)]">Chave de API</h2>
            </div>

            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm font-[family-name:var(--font-mono)] text-[var(--color-text-muted)] overflow-hidden text-ellipsis whitespace-nowrap">
                {apiKeyVisible ? apiKeyFull : apiKeyMasked}
              </code>
              <button
                onClick={() => setApiKeyVisible((v) => !v)}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] hover:bg-white/5 transition-colors cursor-pointer"
              >
                {apiKeyVisible ? (
                  <EyeOff className="h-3.5 w-3.5" />
                ) : (
                  <Eye className="h-3.5 w-3.5" />
                )}
              </button>
              <CopyButton text={apiKeyFull} />
            </div>

            <div className="mt-4 flex items-center justify-between">
              <p className="text-xs text-[var(--color-text-muted)]">
                Criada em 12/01/2026 · Nunca expirada
              </p>
              <button
                onClick={() => { setRotateConfirmError(null); setShowRotateConfirm(true); }}
                disabled={rotating}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                  rotated
                    ? "text-green-400 bg-green-900/20"
                    : "text-amber-400 bg-amber-900/20 hover:bg-amber-900/30"
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {rotated ? (
                  <>
                    <Check className="h-3.5 w-3.5" />
                    Chave rotacionada
                  </>
                ) : (
                  <>
                    <RefreshCw className={`h-3.5 w-3.5 ${rotating ? "animate-spin" : ""}`} />
                    {rotating ? "Rotacionando..." : "Rotacionar chave"}
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Usage stats */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <h2 className="text-sm font-semibold text-[var(--color-text)] mb-4">
              Uso (acumulado)
            </h2>
            <div className="grid grid-cols-3 gap-4">
              {[
                {
                  label: "Requests",
                  value: stats.total_requests >= 1_000_000
                    ? `${(stats.total_requests / 1_000_000).toFixed(2)}M`
                    : stats.total_requests >= 1_000
                    ? `${(stats.total_requests / 1_000).toFixed(1)}k`
                    : stats.total_requests.toString(),
                  sub: `${stats.bypasses.toLocaleString("pt-BR")} desviados`,
                },
                {
                  label: "Tokens economizados",
                  value: stats.tokens_saved >= 1_000_000
                    ? `${(stats.tokens_saved / 1_000_000).toFixed(1)}M`
                    : `${(stats.tokens_saved / 1_000).toFixed(0)}k`,
                  sub: `$ ${stats.cost_saved.toFixed(2)} em custo evitado`,
                },
                {
                  label: "Latência P95",
                  value: stats.avg_latency_ms > 0 ? `${stats.avg_latency_ms}ms` : "—",
                  sub: stats.avg_latency_ms > 0 && stats.avg_latency_ms < 300
                    ? "Meta: < 300ms ✓"
                    : stats.avg_latency_ms >= 300
                    ? "⚠ Acima da meta"
                    : "Sem dados",
                },
              ].map((stat) => (
                <div key={stat.label} className="rounded-lg bg-white/5 p-4">
                  <p className="text-xs text-[var(--color-text-muted)] mb-1">{stat.label}</p>
                  <p className="text-xl font-bold font-[family-name:var(--font-mono)] text-[var(--color-text)]">
                    {stat.value}
                  </p>
                  <p className="text-[10px] text-[var(--color-text-muted)]/60 mt-0.5">
                    {stat.sub}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Rate limits */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <h2 className="text-sm font-semibold text-[var(--color-text)] mb-4">
              Rate limits (plano Enterprise)
            </h2>
            <div className="space-y-3">
              {[
                { label: "Requests por segundo", limit: "500 RPS", used: 62 },
                { label: "Requests por minuto", limit: "20.000 RPM", used: 41 },
                { label: "Tokens por dia", limit: "Ilimitado", used: 0 },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-4">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-[var(--color-text-muted)]">{item.label}</span>
                      <span className="text-xs font-medium text-[var(--color-text)]">
                        {item.limit}
                      </span>
                    </div>
                    {item.used > 0 && (
                      <div className="h-1 rounded-full bg-white/10">
                        <div
                          className="h-full rounded-full bg-[var(--color-primary)]/60"
                          style={{ width: `${item.used}%` }}
                        />
                      </div>
                    )}
                  </div>
                  {item.used > 0 && (
                    <span className="text-xs text-[var(--color-text-muted)] w-10 text-right">
                      {item.used}%
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── TAB: Controles avançados ─────────────────────────── */}
      {activeTab === "controles" && (
        <div className="space-y-5">
          {/* Active warning — shown when KS is on */}
          {!ksLoading && ksActive && (
            <div className="flex items-center justify-between gap-4 rounded-2xl border-2 border-red-500/70 bg-gradient-to-r from-red-950/80 to-red-900/40 px-6 py-4 shadow-lg shadow-red-950/30">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-red-500/20">
                  <Power className="h-6 w-6 animate-pulse text-red-400" />
                </div>
                <div>
                  <p className="text-sm font-bold uppercase tracking-widest text-red-300">
                    ● KILL SWITCH ATIVO
                  </p>
                  <p className="mt-0.5 text-xs text-red-400">
                    AION está parado — nenhum request está sendo processado
                    {ksReason && <> · Motivo: <span className="font-semibold">&quot;{ksReason}&quot;</span></>}
                    {ksExpires && <> · Expira: {new Date(ksExpires * 1000).toLocaleTimeString("pt-BR")}</>}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowKsDeactivateConfirm(true)}
                disabled={ksDeactivating}
                className="shrink-0 cursor-pointer rounded-lg border border-red-500/50 bg-red-900/50 px-4 py-2 text-sm font-semibold text-red-300 transition-colors hover:bg-red-800/50 disabled:opacity-50"
              >
                {ksDeactivating ? "Desativando…" : "Desativar"}
              </button>
            </div>
          )}

          {/* Kill switch — main control card */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-red-900/20 ring-1 ring-red-800/40">
                <Power className="h-5 w-5 text-red-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-semibold text-[var(--color-text)]">Kill Switch</h2>
                  {!ksLoading && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                      ksActive
                        ? "bg-red-500/20 text-red-300"
                        : "bg-emerald-500/15 text-emerald-300"
                    }`}>
                      {ksActive ? "● Ativo" : "○ Inativo"}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  Para todo o AION imediatamente, recusando 100% das requisições. Use apenas em emergências —
                  vazamentos confirmados, ataque ativo, comprometimento de credenciais.
                </p>
                <div className="mt-3 rounded-lg border border-amber-800/40 bg-amber-900/10 px-3 py-2">
                  <div className="flex items-start gap-2 text-xs text-amber-300">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span>
                      Após ativado, todo tráfego será respondido com erro até a desativação manual.
                      Coordene com a equipe antes de acionar.
                    </span>
                  </div>
                </div>
              </div>
              {!ksLoading && !ksActive && (
                <button
                  onClick={() => setShowKsActivateModal(true)}
                  className="shrink-0 cursor-pointer rounded-lg border border-red-800/50 bg-red-950/30 px-4 py-2 text-sm font-semibold text-red-400 transition-colors hover:bg-red-900/40 hover:text-red-300"
                >
                  Ativar Kill Switch
                </button>
              )}
            </div>
          </div>

          {/* Where to find module on/off */}
          <div className="rounded-xl border border-dashed border-[var(--color-border)] bg-white/[0.02] p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/5">
                <ShieldAlert className="h-4 w-4 text-[var(--color-text-muted)]" />
              </div>
              <div className="flex-1">
                <h3 className="text-sm font-semibold text-[var(--color-text)]">Liga/desliga de módulos</h3>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  Para ligar ou desligar Proteção, Roteamento ou Otimização individualmente, use os toggles em{" "}
                  <a href="/operations" className="font-semibold text-[var(--color-primary)] hover:underline">Operação → Módulos ativos</a>.
                  Cada toggle exige um motivo registrado.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      <ConfirmActionModal
        open={showRotateConfirm}
        severity="critical"
        title="Rotacionar chaves de API?"
        description="Todas as chaves ativas serão revogadas e substituídas por novas chaves geradas."
        impact={[
          "• Integrações existentes perderão acesso imediatamente após a rotação",
          "• O AION_ADMIN_KEY no backend deve ser atualizado com a nova chave",
          "• Coordene com os times que usam a API antes de rotacionar",
        ]}
        actionLabel="Rotacionar chaves"
        loading={rotating}
        error={rotateConfirmError}
        onConfirm={handleRotateConfirm}
        onCancel={() => setShowRotateConfirm(false)}
      />

      {/* Kill Switch — Activate Modal */}
      {showKsActivateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-[var(--color-surface)] p-8 shadow-2xl">
            <div className="mb-5 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-900/40">
                <Power className="h-5 w-5 text-red-400" />
              </div>
              <h3 className="text-lg font-bold text-[var(--color-text)]">Ativar Kill Switch?</h3>
            </div>
            <p className="text-sm text-[var(--color-text-muted)]">
              Esta ação para <strong className="text-[var(--color-text)]">imediatamente</strong> todo o tráfego processado pelo AION. Use apenas em situações de emergência.
            </p>
            <div className="mt-5">
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Motivo (obrigatório)
              </label>
              <input
                type="text"
                value={ksReasonInput}
                onChange={(e) => setKsReasonInput(e.target.value)}
                placeholder="Ex: vazamento de dados detectado, ataque em andamento..."
                autoFocus
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none focus:border-red-600 placeholder:text-[var(--color-text-muted)]/50"
              />
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => { setShowKsActivateModal(false); setKsReasonInput(""); }}
                className="cursor-pointer rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                Cancelar
              </button>
              <button
                onClick={handleActivateKs}
                disabled={!ksReasonInput.trim() || ksActivating}
                className="cursor-pointer rounded-lg bg-red-600 px-4 py-2 text-sm font-bold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {ksActivating ? "Ativando…" : "Confirmar — Parar AION"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Kill Switch — Deactivate Confirm */}
      <ConfirmActionModal
        open={showKsDeactivateConfirm}
        severity="critical"
        title="Desativar Kill Switch?"
        description="O AION voltará a processar requisições normalmente. Confirme que a situação de emergência foi resolvida."
        impact={[
          "• Todo tráfego voltará a fluir pelo pipeline imediatamente",
          "• As proteções de emergência do Kill Switch serão removidas",
          "• Registre no motivo a confirmação de que o incidente foi resolvido",
        ]}
        actionLabel="Retomar operação"
        loading={ksDeactivating}
        error={ksDeactivateError}
        onConfirm={handleDeactivateKs}
        onCancel={() => setShowKsDeactivateConfirm(false)}
      />
    </div>
  );
}
