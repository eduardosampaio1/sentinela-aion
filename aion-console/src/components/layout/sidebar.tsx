"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import {
  Activity,
  SlidersHorizontal,
  GitBranch,
  Shield,
  Radio,
  FlaskConical,
  MessagesSquare,
  TrendingDown,
  Users,
  FileBarChart,
  Settings,
  HelpCircle,
  PanelLeftClose,
  PanelLeftOpen,
  UserPlus,
  X,
  CheckCircle2,
  ChevronDown,
  Brain,
  Network,
  Cpu,
} from "lucide-react";
import { Logo } from "./logo";
import { mockAdminRoles } from "@/lib/mock-data";
import { getHealth, type HealthInfo } from "@/lib/api/observability";

// ── Mode label helpers ────────────────────────────────────────────────────────

const MODE_LABELS: Record<string, string> = {
  poc_decision:    "POC Decision-Only",
  poc_transparent: "POC Transparent",
  full_transparent: "Full Transparent",
  decision_only:   "Decision-Only",
  not_configured:  "Modo não configurado",
};

const MODE_COLORS: Record<string, string> = {
  poc_decision:    "text-amber-400 border-amber-800/40 bg-amber-900/10",
  poc_transparent: "text-sky-400 border-sky-800/40 bg-sky-900/10",
  full_transparent: "text-emerald-400 border-emerald-800/40 bg-emerald-900/10",
  decision_only:   "text-violet-400 border-violet-800/40 bg-violet-900/10",
  not_configured:  "text-[var(--color-text-muted)] border-[var(--color-border)] bg-transparent",
};

function ModeLabel({ mode }: { mode: string }) {
  const label = MODE_LABELS[mode] ?? mode;
  const color = MODE_COLORS[mode] ?? MODE_COLORS.not_configured;
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${color}`}>
      {label}
    </span>
  );
}

const navGroups = [
  {
    label: "Core",
    items: [
      { href: "/", label: "Visão Geral", icon: Activity },
      { href: "/operations", label: "Operação", icon: Radio },
    ],
  },
  {
    label: "Inteligência",
    items: [
      { href: "/intelligence", label: "Inteligência NEMOS", icon: Brain },
      { href: "/policies", label: "Comportamento", icon: SlidersHorizontal },
      { href: "/routing", label: "Roteamento", icon: GitBranch },
      { href: "/estixe", label: "Proteção", icon: Shield },
      { href: "/shadow", label: "Shadow Mode", icon: FlaskConical },
    ],
  },
  {
    label: "Plataforma",
    items: [
      { href: "/sessions", label: "Sessões", icon: MessagesSquare },
      { href: "/budget", label: "Economia", icon: TrendingDown },
      { href: "/collective", label: "AION Collective", icon: Network },
      { href: "/reports", label: "Relatórios", icon: FileBarChart },
    ],
  },
];

const bottomItems = [
  { href: "/admin", label: "Admin", icon: Users },
  { href: "/settings", label: "Configurações", icon: Settings },
  { href: "/help", label: "Ajuda", icon: HelpCircle },
];

type InviteStatus = "idle" | "sending" | "sent";

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const pathname = usePathname();
  const [showInvite, setShowInvite] = useState(false);
  const [inviteName, setInviteName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState(mockAdminRoles[3]?.name ?? "Developer");
  const [inviteStatus, setInviteStatus] = useState<InviteStatus>("idle");
  const [healthInfo, setHealthInfo] = useState<HealthInfo | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealthInfo)
      .catch(() => setHealthInfo(null));
  }, []);

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  const handleSendInvite = async () => {
    if (!inviteName.trim() || !inviteEmail.trim()) return;
    setInviteStatus("sending");
    await new Promise((r) => setTimeout(r, 1000));
    setInviteStatus("sent");
    setTimeout(() => {
      setShowInvite(false);
      setInviteName("");
      setInviteEmail("");
      setInviteRole(mockAdminRoles[3]?.name ?? "Developer");
      setInviteStatus("idle");
    }, 1800);
  };

  const handleCloseInvite = () => {
    if (inviteStatus === "sending") return;
    setShowInvite(false);
    setInviteName("");
    setInviteEmail("");
    setInviteRole(mockAdminRoles[3]?.name ?? "Developer");
    setInviteStatus("idle");
  };

  const selectedRole = mockAdminRoles.find((r) => r.name === inviteRole);
  const rolePreview = selectedRole
    ? selectedRole.permissions[0] === "*"
      ? "Acesso total ao sistema"
      : selectedRole.permissions.slice(0, 2).join(", ") +
        (selectedRole.permissions.length > 2
          ? ` +${selectedRole.permissions.length - 2} mais`
          : "")
    : "";

  return (
    <>
      <aside
        className={`fixed left-0 top-0 z-20 flex h-full flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] transition-all duration-200 ${
          collapsed ? "w-16" : "w-60"
        }`}
      >
        {/* Header */}
        <div className="flex h-14 items-center gap-3 border-b border-[var(--color-border)] px-4">
          <Logo size={28} />
          {!collapsed && (
            <span className="font-[family-name:var(--font-heading)] text-sm font-bold text-[var(--color-primary)]">
              Sentinela AION
            </span>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {navGroups.map((group, gi) => (
            <div key={group.label} className={gi > 0 ? "mt-4" : ""}>
              {!collapsed && (
                <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-[var(--color-text-muted)]/50">
                  {group.label}
                </p>
              )}
              {collapsed && gi > 0 && (
                <div className="mx-3 mb-2 h-px bg-[var(--color-border)]" />
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150 ${
                        active
                          ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                          : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)]"
                      } ${collapsed ? "justify-center" : ""}`}
                      title={collapsed ? item.label : undefined}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      {!collapsed && <span>{item.label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Mode badge strip */}
        {healthInfo && (
          <div className="border-t border-[var(--color-border)] px-3 py-2">
            {collapsed ? (
              /* Collapsed: just a colored dot */
              <div
                title={MODE_LABELS[healthInfo.aion_mode ?? ""] ?? healthInfo.aion_mode ?? "Modo não configurado"}
                className="flex justify-center"
              >
                <Cpu className={`h-4 w-4 ${
                  healthInfo.aion_mode === "poc_decision" ? "text-amber-400" :
                  healthInfo.aion_mode === "poc_transparent" ? "text-sky-400" :
                  healthInfo.aion_mode === "full_transparent" ? "text-emerald-400" :
                  healthInfo.aion_mode === "decision_only" ? "text-violet-400" :
                  "text-[var(--color-text-muted)]"
                }`} />
              </div>
            ) : (
              /* Expanded: full badge with status pills */
              <div className="space-y-1.5">
                <ModeLabel mode={healthInfo.aion_mode ?? "not_configured"} />
                <div className="flex flex-wrap gap-1">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border ${healthInfo.executes_llm ? "text-sky-400 border-sky-800/40 bg-sky-900/10" : "text-[var(--color-text-muted)] border-[var(--color-border)]"}`}>
                    LLM {healthInfo.executes_llm ? "ativo" : "externo"}
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border ${healthInfo.telemetry_enabled ? "text-orange-400 border-orange-800/40 bg-orange-900/10" : "text-[var(--color-text-muted)] border-[var(--color-border)]"}`}>
                    Telemetria {healthInfo.telemetry_enabled ? "on" : "off"}
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border ${healthInfo.collective_enabled ? "text-purple-400 border-purple-800/40 bg-purple-900/10" : "text-[var(--color-text-muted)] border-[var(--color-border)]"}`}>
                    Collective {healthInfo.collective_enabled ? (healthInfo.aion_mode === "poc_decision" ? "catálogo" : "on") : "off"}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Bottom */}
        <div className="border-t border-[var(--color-border)] px-2 py-3 space-y-0.5">
          {/* Invite button */}
          {!collapsed ? (
            <button
              onClick={() => setShowInvite(true)}
              className="flex w-full items-center gap-3 rounded-lg border border-dashed border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-text-muted)] transition-all duration-150 hover:border-[var(--color-primary)]/40 hover:bg-[var(--color-primary)]/5 hover:text-[var(--color-primary)] cursor-pointer mb-1.5"
            >
              <UserPlus className="h-4 w-4 shrink-0" />
              <span>Convidar colega</span>
            </button>
          ) : (
            <button
              onClick={() => setShowInvite(true)}
              title="Convidar colega"
              className="flex w-full items-center justify-center rounded-lg px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors duration-150 hover:bg-white/5 hover:text-[var(--color-text)] cursor-pointer mb-1.5"
            >
              <UserPlus className="h-4 w-4" />
            </button>
          )}

          {/* Admin + Settings + Ajuda */}
          {bottomItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-150 ${
                  active
                    ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)] font-medium"
                    : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)]"
                } ${collapsed ? "justify-center" : ""}`}
                title={collapsed ? item.label : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}

          {/* Collapse toggle */}
          <button
            onClick={onToggle}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors duration-150 hover:bg-white/5 hover:text-[var(--color-text)] cursor-pointer ${
              collapsed ? "justify-center" : ""
            }`}
            aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
          >
            {collapsed ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <>
                <PanelLeftClose className="h-4 w-4" />
                <span>Recolher</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* ── Invite modal ─────────────────────────────────────── */}
      {showInvite && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) handleCloseInvite();
          }}
        >
          <div className="w-full max-w-sm rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-2xl">
            {inviteStatus === "sent" ? (
              /* Success state */
              <div className="flex flex-col items-center gap-3 py-6 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-green-900/30">
                  <CheckCircle2 className="h-7 w-7 text-green-400" />
                </div>
                <p className="text-base font-semibold text-[var(--color-text)]">
                  Convite enviado!
                </p>
                <p className="text-sm text-[var(--color-text-muted)]">
                  <span className="font-medium text-[var(--color-text)]">{inviteEmail}</span>{" "}
                  receberá o link de acesso em breve.
                </p>
              </div>
            ) : (
              <>
                {/* Header */}
                <div className="flex items-start justify-between mb-5">
                  <div>
                    <h3 className="text-base font-semibold text-[var(--color-text)]">
                      Convidar colega
                    </h3>
                    <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                      O convite será enviado por e-mail
                    </p>
                  </div>
                  <button
                    onClick={handleCloseInvite}
                    className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)] transition-colors cursor-pointer"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                {/* Fields */}
                <div className="space-y-4">
                  {/* Name */}
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
                      Nome completo
                    </label>
                    <input
                      type="text"
                      value={inviteName}
                      onChange={(e) => setInviteName(e.target.value)}
                      placeholder="João Silva"
                      className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm text-[var(--color-text)] placeholder-[var(--color-text-muted)]/40 outline-none focus:border-[var(--color-primary)]/60 transition-colors"
                    />
                  </div>

                  {/* Email */}
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
                      E-mail corporativo
                    </label>
                    <input
                      type="email"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      placeholder="joao@empresa.com"
                      className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm text-[var(--color-text)] placeholder-[var(--color-text-muted)]/40 outline-none focus:border-[var(--color-primary)]/60 transition-colors"
                    />
                  </div>

                  {/* Role */}
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-[var(--color-text-muted)]">
                      Papel no sistema
                    </label>
                    <div className="relative">
                      <select
                        value={inviteRole}
                        onChange={(e) => setInviteRole(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 pr-8 text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-primary)]/60 transition-colors cursor-pointer"
                      >
                        {mockAdminRoles.map((role) => (
                          <option key={role.name} value={role.name}>
                            {role.name}
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--color-text-muted)]" />
                    </div>
                    {rolePreview && (
                      <p className="mt-1.5 text-[10px] font-[family-name:var(--font-mono)] text-[var(--color-text-muted)]/60 leading-relaxed">
                        {rolePreview}
                      </p>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="mt-6 flex gap-3">
                  <button
                    onClick={handleCloseInvite}
                    className="flex-1 rounded-lg border border-[var(--color-border)] py-2 text-sm font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors cursor-pointer"
                  >
                    Cancelar
                  </button>
                  <button
                    onClick={handleSendInvite}
                    disabled={
                      !inviteName.trim() ||
                      !inviteEmail.trim() ||
                      inviteStatus === "sending"
                    }
                    className="flex-1 rounded-lg bg-[var(--color-cta)] py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                  >
                    {inviteStatus === "sending" ? "Enviando..." : "Enviar convite"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
