"use client";

import { useState } from "react";
import { Users, Shield, Key, RefreshCw, CheckCircle2, AlertCircle, Clock, FileText, Trash2, Lock, Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DemoBanner } from "@/components/ui/demo-banner";
import { useApiData } from "@/lib/use-api-data";
import { mockAdminRoles, mockIdentityProviders } from "@/lib/mock-data";
import { rotateKeys, getAudit, getComplianceSummary, deleteTenantData, getActiveTenant } from "@/lib/api";

const roleColors: Record<string, string> = {
  red: "bg-red-900/30 text-red-400 border-red-800/50",
  orange: "bg-orange-900/30 text-orange-400 border-orange-800/50",
  yellow: "bg-yellow-900/30 text-yellow-400 border-yellow-800/50",
  sky: "bg-sky-900/30 text-sky-400 border-sky-800/50",
  slate: "bg-slate-800/60 text-slate-400 border-slate-700/50",
};

const idpStatusConfig: Record<string, { icon: React.ReactNode; badge: "success" | "warning" | "error" }> = {
  connected: { icon: <CheckCircle2 className="h-4 w-4 text-green-400" />, badge: "success" },
  pending: { icon: <Clock className="h-4 w-4 text-amber-400" />, badge: "warning" },
  error: { icon: <AlertCircle className="h-4 w-4 text-red-400" />, badge: "error" },
};

const tabs = ["Papéis & Permissões", "Provedores de Identidade", "Segurança de Acesso", "Audit Log", "Compliance & LGPD"] as const;
type Tab = (typeof tabs)[number];

type AdminActionType = "create-role" | "edit-role" | "connect-idp" | "configure-idp" | "rotate-keys" | "session-timeout" | "configure-mfa" | "manage-allowlist";

export function AdminPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Papéis & Permissões");
  const [selectedAction, setSelectedAction] = useState<AdminActionType | null>(null);
  const [selectedRoleName, setSelectedRoleName] = useState<string | null>(null);
  const [selectedIdPName, setSelectedIdPName] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [keysRotatedAt, setKeysRotatedAt] = useState<Date | null>(null);
  const [rotateReason, setRotateReason] = useState("");

  const handleOpenConfirm = (actionType: AdminActionType, roleName?: string, idpName?: string) => {
    setSelectedAction(actionType);
    if (roleName) setSelectedRoleName(roleName);
    if (idpName) setSelectedIdPName(idpName);
    setSaveError(null);
    setRotateReason("");
    setShowConfirm(true);
  };

  const handleConfirm = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      if (selectedAction === "rotate-keys") {
        await rotateKeys([], rotateReason.trim() || undefined);
        setKeysRotatedAt(new Date());
      } else {
        // Actions without backend endpoint yet — simulate locally
        await new Promise(resolve => setTimeout(resolve, 800));
      }
      setShowConfirm(false);
      setSelectedAction(null);
      setSelectedRoleName(null);
      setSelectedIdPName(null);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Erro ao processar ação");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setShowConfirm(false);
    setSaveError(null);
    setSelectedAction(null);
    setSelectedRoleName(null);
    setSelectedIdPName(null);
    setRotateReason("");
  };

  const getConfirmTitle = (): string => {
    switch (selectedAction) {
      case "create-role":
        return "Criar novo papel?";
      case "edit-role":
        return `Editar papel "${selectedRoleName}"?`;
      case "connect-idp":
        return "Conectar provedor de identidade?";
      case "configure-idp":
        return `Configurar "${selectedIdPName}"?`;
      case "rotate-keys":
        return "Rotacionar chaves HMAC?";
      case "session-timeout":
        return "Alterar tempo de sessão admin?";
      case "configure-mfa":
        return "Configurar autenticação multifator?";
      case "manage-allowlist":
        return "Gerenciar IP allowlist?";
      default:
        return "Confirmar ação?";
    }
  };

  const getConfirmDescription = (): string => {
    switch (selectedAction) {
      case "create-role":
        return "Um novo papel será criado com permissões padrão. Você poderá editar permissões após a criação.";
      case "edit-role":
        return `As permissões do papel "${selectedRoleName}" serão alteradas. Usuários com este papel terão suas permissões atualizadas imediatamente.`;
      case "connect-idp":
        return "Um novo provedor de identidade será conectado ao sistema. Credenciais serão validadas automaticamente.";
      case "configure-idp":
        return `A configuração do "${selectedIdPName}" será alterada. Novas sincronizações usarão os novos parâmetros.`;
      case "rotate-keys":
        return "As chaves HMAC serão rotacionadas. O serviço continuará operacional durante a rotação.";
      case "session-timeout":
        return "O tempo de expiração de sessão admin será alterado. Sessões ativas não serão interrompidas.";
      case "configure-mfa":
        return "Autenticação multifator será configurada. Afetará usuários com Super Admin e Security Analyst.";
      case "manage-allowlist":
        return "O allowlist de IP será atualizado. Apenas IPs na lista poderão acessar.";
      default:
        return "Você está prestes a executar uma ação importante.";
    }
  };

  const getImpactPoints = (): string[] => {
    switch (selectedAction) {
      case "create-role":
        return [
          "Novo papel será adicionado ao sistema",
          "Disponível imediatamente para atribuição de usuários",
          "Permissões padrão serão aplicadas"
        ];
      case "edit-role":
        return [
          `Todos os usuários com o papel "${selectedRoleName}" terão permissões atualizadas`,
          "Mudanças são imediatas",
          "Usuários já logados precisarão fazer novo login para ver novas permissões"
        ];
      case "connect-idp":
        return [
          "Credenciais serão validadas",
          "Sincronização de usuários começará",
          "Novo método de autenticação será disponibilizado"
        ];
      case "configure-idp":
        return [
          "Configuração será aplicada imediatamente",
          "Próximas sincronizações usarão os novos parâmetros",
          "Usuários existentes não serão desconectados"
        ];
      case "rotate-keys":
        return [
          "Novas chaves HMAC serão geradas",
          "Chaves antigas continuarão válidas por 24 horas",
          "Zero downtime esperado"
        ];
      case "session-timeout":
        return [
          "Novo tempo será aplicado a novas sessões",
          "Sessões ativas não serão afetadas",
          "Configuração será global para todos os admins"
        ];
      case "configure-mfa":
        return [
          "MFA será obrigatório para Super Admin e Security Analyst",
          "Usuários terão 24 horas para configurar autenticador",
          "Sem MFA configurado, acesso será bloqueado"
        ];
      case "manage-allowlist":
        return [
          "Apenas IPs na lista poderão acessar",
          "Requisições de IPs fora da lista serão rejeitadas",
          "Certifique-se que sua IP está na lista antes de salvar"
        ];
      default:
        return [];
    }
  };

  // ─── Audit Log ────────────────────────────────────────────────────────────
  const { data: auditRaw, isDemo: auditIsDemo, refetch: refetchAudit } = useApiData(
    () => getAudit(100),
    [] as Record<string, unknown>[],
    { intervalMs: activeTab === "Audit Log" ? 30_000 : undefined },
  );

  // ─── Compliance & LGPD ────────────────────────────────────────────────────
  const mockComplianceFallback: Record<string, unknown> = {
    decisions: { total_requests: 0, blocked: 0, bypassed: 0, passed_to_llm: 0, block_rate: 0 },
    pii: { total_intercepts: 0, by_category: {}, note: "" },
    session_audit: { sessions_with_audit_trail: 0, audit_trail_signed: false, audit_ttl_days: 90 },
    infrastructure: { multi_turn_context_enabled: false, budget_cap_enabled: false, data_residency: "not_configured", audit_hash_chaining: false },
    report_signature: "",
  };
  const { data: compliance, isDemo: complianceIsDemo, refetch: refetchCompliance } = useApiData(
    getComplianceSummary,
    mockComplianceFallback,
    { intervalMs: activeTab === "Compliance & LGPD" ? 120_000 : undefined },
  );
  const [showLgpdModal, setShowLgpdModal] = useState(false);
  const [lgpdConfirmText, setLgpdConfirmText] = useState("");
  const [lgpdReason, setLgpdReason] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteSuccess, setDeleteSuccess] = useState(false);

  const handleLgpdDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteTenantData(getActiveTenant(), lgpdReason.trim() || undefined);
      setDeleteSuccess(true);
      setShowLgpdModal(false);
      setLgpdConfirmText("");
      setLgpdReason("");
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Erro ao excluir dados");
    } finally {
      setDeleting(false);
    }
  };

  const getActionButtonLabel = (): string => {
    switch (selectedAction) {
      case "create-role":
      case "connect-idp":
        return "Criar";
      case "edit-role":
      case "configure-idp":
      case "configure-mfa":
      case "manage-allowlist":
        return "Salvar";
      case "rotate-keys":
        return "Rotacionar";
      case "session-timeout":
        return "Alterar";
      default:
        return "Confirmar";
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
          Administração
        </h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          RBAC, provedores de identidade e configurações de segurança de acesso
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--color-border)]">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab
                ? "border-[var(--color-primary)] text-[var(--color-primary)]"
                : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Roles tab */}
      {activeTab === "Papéis & Permissões" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-[var(--color-text-muted)]">
              {mockAdminRoles.reduce((s, r) => s + r.users, 0)} usuários em {mockAdminRoles.length} papéis
            </p>
            <button
              onClick={() => handleOpenConfirm("create-role")}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--color-primary)]/10 px-3 py-1.5 text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary)]/20 transition-colors"
            >
              <Users className="h-3.5 w-3.5" />
              Novo papel
            </button>
          </div>

          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)]">
                  {["Papel", "Usuários", "Permissões", ""].map((h) => (
                    <th key={h} className="px-5 py-3 text-left text-xs font-medium text-[var(--color-text-muted)]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {mockAdminRoles.map((role) => (
                  <tr key={role.name} className="border-b border-[var(--color-border)]/50 hover:bg-white/5 transition-colors">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${
                            roleColors[role.color] ?? roleColors.slate
                          }`}
                        >
                          {role.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-4 text-[var(--color-text)]">{role.users}</td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap gap-1">
                        {role.permissions.slice(0, 3).map((p) => (
                          <code key={p} className="rounded bg-white/5 px-1.5 py-0.5 text-xs text-[var(--color-text-muted)]">
                            {p}
                          </code>
                        ))}
                        {role.permissions.length > 3 && (
                          <span className="text-xs text-[var(--color-text-muted)]">
                            +{role.permissions.length - 3}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <button
                        onClick={() => handleOpenConfirm("edit-role", role.name)}
                        className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
                      >
                        Editar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* IdP tab */}
      {activeTab === "Provedores de Identidade" && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button
              onClick={() => handleOpenConfirm("connect-idp")}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--color-primary)]/10 px-3 py-1.5 text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary)]/20 transition-colors"
            >
              <Shield className="h-3.5 w-3.5" />
              Conectar IdP
            </button>
          </div>

          <div className="grid gap-4">
            {mockIdentityProviders.map((idp) => {
              const sc = idpStatusConfig[idp.status];
              return (
                <div
                  key={idp.name}
                  className="flex items-center justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
                >
                  <div className="flex items-center gap-4">
                    {sc.icon}
                    <div>
                      <p className="text-sm font-semibold text-[var(--color-text)]">{idp.name}</p>
                      <p className="text-xs text-[var(--color-text-muted)]">
                        {idp.type} · {idp.users > 0 ? `${idp.users} usuários sincronizados` : "Aguardando configuração"}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={sc.badge}>
                      {idp.status === "connected" ? "Conectado" : idp.status === "pending" ? "Pendente" : "Erro"}
                    </Badge>
                    <button
                      onClick={() => handleOpenConfirm("configure-idp", undefined, idp.name)}
                      className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
                    >
                      Configurar
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Security tab */}
      {activeTab === "Segurança de Acesso" && (
        <div className="space-y-4">
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] divide-y divide-[var(--color-border)]">
            {[
              {
                label: "Rotação de chaves HMAC",
                desc: keysRotatedAt
                  ? `Última rotação: agora às ${keysRotatedAt.toLocaleTimeString("pt-BR")}`
                  : "Última rotação: 7 dias atrás",
                action: "Rotacionar agora",
                icon: RefreshCw,
                status: keysRotatedAt ? "ok" : "ok",
                actionType: "rotate-keys" as AdminActionType,
              },
              { label: "Tempo de sessão admin", desc: "Expiração automática em 8 horas", action: "Alterar", icon: Clock, status: "ok", actionType: "session-timeout" as AdminActionType },
              { label: "Autenticação multifator", desc: "Obrigatório para Super Admin e Security Analyst", action: "Configurar", icon: Shield, status: "ok", actionType: "configure-mfa" as AdminActionType },
              { label: "IP allowlist", desc: "4 faixas de IP configuradas", action: "Gerenciar", icon: Key, status: "warning", actionType: "manage-allowlist" as AdminActionType },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.label} className="flex items-center justify-between px-5 py-4">
                  <div className="flex items-center gap-3">
                    <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                      item.status === "ok" ? "bg-green-900/30" : "bg-amber-900/30"
                    }`}>
                      <Icon className={`h-4 w-4 ${item.status === "ok" ? "text-green-400" : "text-amber-400"}`} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-[var(--color-text)]">{item.label}</p>
                      <p className="text-xs text-[var(--color-text-muted)]">{item.desc}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => handleOpenConfirm(item.actionType)}
                    className="text-xs text-[var(--color-primary)] hover:underline"
                  >
                    {item.action}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Audit Log tab */}
      {activeTab === "Audit Log" && (
        <div className="space-y-4">
          {auditIsDemo && <DemoBanner onRetry={refetchAudit} />}

          <div className="flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-sm text-[var(--color-text-muted)]">
              <FileText className="h-4 w-4" />
              Registro imutável de todas as ações administrativas
            </p>
            <button
              onClick={refetchAudit}
              className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Atualizar
            </button>
          </div>

          {auditRaw.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-16 text-center">
              <FileText className="h-8 w-8 text-[var(--color-text-muted)] mb-3 opacity-40" />
              <p className="text-sm font-medium text-[var(--color-text)]">Nenhum evento de auditoria</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                Ações administrativas aparecerão aqui
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-border)]">
                      {["Timestamp", "Ação", "Operador", "IP", "Status"].map((h) => (
                        <th key={h} className="px-5 py-3 text-left text-xs font-medium text-[var(--color-text-muted)]">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(auditRaw as Record<string, unknown>[]).map((entry, idx) => {
                      const ts = entry.timestamp
                        ? new Date(
                            typeof entry.timestamp === "number"
                              ? entry.timestamp * 1000
                              : String(entry.timestamp),
                          ).toLocaleString("pt-BR", {
                            day: "2-digit",
                            month: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })
                        : "—";
                      const action = String(entry.action ?? entry.event ?? entry.type ?? "—");
                      const operator = String(entry.admin ?? entry.user ?? entry.operator ?? "sistema");
                      const ip = String(entry.ip ?? entry.source_ip ?? "—");
                      const status = String(entry.result ?? entry.status ?? "ok");
                      const isOk = status === "ok" || status === "success";

                      return (
                        <tr
                          key={idx}
                          className="border-b border-[var(--color-border)]/50 hover:bg-white/5 transition-colors"
                        >
                          <td className="px-5 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                            {ts}
                          </td>
                          <td className="px-5 py-3">
                            <code className="rounded bg-white/5 px-1.5 py-0.5 text-xs text-[var(--color-text)]">
                              {action}
                            </code>
                          </td>
                          <td className="px-5 py-3 text-xs text-[var(--color-text)]">{operator}</td>
                          <td className="px-5 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                            {ip}
                          </td>
                          <td className="px-5 py-3">
                            <Badge variant={isOk ? "success" : "error"}>
                              {isOk ? "OK" : status}
                            </Badge>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Compliance & LGPD tab */}
      {activeTab === "Compliance & LGPD" && (
        <div className="space-y-6">
          {complianceIsDemo && <DemoBanner onRetry={refetchCompliance} />}

          {deleteSuccess && (
            <div className="flex items-center gap-2 rounded-xl border border-green-800/50 bg-green-900/20 px-4 py-3 text-sm text-green-400">
              <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
              Dados do tenant excluídos com sucesso (LGPD Art. 18).
            </div>
          )}

          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[var(--color-text)]">Relatório de Compliance</h2>
              <p className="text-xs text-[var(--color-text-muted)]">Artefato verificável para equipes de compliance e CISO</p>
            </div>
            <button
              onClick={refetchCompliance}
              className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Atualizar
            </button>
          </div>

          {/* Decisions */}
          {(() => {
            const dec = (compliance.decisions ?? {}) as Record<string, unknown>;
            const pii = (compliance.pii ?? {}) as Record<string, unknown>;
            const audit = (compliance.session_audit ?? {}) as Record<string, unknown>;
            const infra = (compliance.infrastructure ?? {}) as Record<string, unknown>;
            const total = (dec.total_requests as number) ?? 0;
            const blocked = (dec.blocked as number) ?? 0;
            const bypassed = (dec.bypassed as number) ?? 0;
            const passed = (dec.passed_to_llm as number) ?? 0;
            const blockRate = (dec.block_rate as number) ?? 0;
            const piiTotal = (pii.total_intercepts as number) ?? 0;
            const piiByCategory = (pii.by_category ?? {}) as Record<string, number>;
            const signed = (audit.audit_trail_signed as boolean) ?? false;
            const ttlDays = (audit.audit_ttl_days as number) ?? 90;
            const multiTurn = (infra.multi_turn_context_enabled as boolean) ?? false;
            const budgetCap = (infra.budget_cap_enabled as boolean) ?? false;
            const dataResidency = (infra.data_residency as string) ?? "—";
            const chainEnabled = (infra.audit_hash_chaining as boolean) ?? false;
            const sig = (compliance.report_signature as string) ?? "";

            return (
              <div className="space-y-4">
                {/* Metrics grid */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: "Total de requests", value: total.toLocaleString("pt-BR"), icon: <Database className="h-4 w-4" />, color: "text-[var(--color-text)]" },
                    { label: "Bloqueados", value: blocked.toLocaleString("pt-BR"), icon: <Shield className="h-4 w-4" />, color: "text-red-400" },
                    { label: "Taxa de bloqueio", value: `${(blockRate * 100).toFixed(2)}%`, icon: <Lock className="h-4 w-4" />, color: "text-orange-400" },
                    { label: "PIIs interceptados", value: piiTotal.toLocaleString("pt-BR"), icon: <Users className="h-4 w-4" />, color: "text-amber-400" },
                  ].map((m) => (
                    <div key={m.label} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-xs text-[var(--color-text-muted)]">{m.label}</p>
                        <span className="text-[var(--color-text-muted)] opacity-40">{m.icon}</span>
                      </div>
                      <p className={`text-xl font-bold ${m.color}`}>{m.value}</p>
                    </div>
                  ))}
                </div>

                {/* Decision distribution bar */}
                {total > 0 && (
                  <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
                    <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                      Distribuição de decisões
                    </p>
                    <div className="flex h-3 w-full overflow-hidden rounded-full">
                      <div className="bg-red-500" style={{ width: `${(blocked / total) * 100}%` }} title={`Bloqueados: ${blocked}`} />
                      <div className="bg-teal-500" style={{ width: `${(bypassed / total) * 100}%` }} title={`Bypass: ${bypassed}`} />
                      <div className="bg-sky-500" style={{ width: `${(passed / total) * 100}%` }} title={`Roteados: ${passed}`} />
                    </div>
                    <div className="mt-2 flex gap-4 text-xs text-[var(--color-text-muted)]">
                      <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-red-500" /> Bloqueado ({((blocked / total) * 100).toFixed(1)}%)</span>
                      <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-teal-500" /> Bypass ({((bypassed / total) * 100).toFixed(1)}%)</span>
                      <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-sky-500" /> Roteado ({((passed / total) * 100).toFixed(1)}%)</span>
                    </div>
                  </div>
                )}

                {/* PII + Infra side by side */}
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
                    <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                      Categorias de PII interceptadas
                    </p>
                    {Object.keys(piiByCategory).length === 0 ? (
                      <p className="text-xs text-[var(--color-text-muted)] italic">Nenhuma categoria registrada</p>
                    ) : (
                      <div className="space-y-1.5">
                        {Object.entries(piiByCategory).map(([cat, count]) => (
                          <div key={cat} className="flex items-center justify-between text-sm">
                            <span className="text-[var(--color-text-muted)]">{cat}</span>
                            <span className="font-semibold text-amber-400">{count}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <p className="mt-3 text-xs text-[var(--color-text-muted)] italic">
                      Conteúdo PII nunca é armazenado — apenas rótulos de categoria.
                    </p>
                  </div>

                  <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
                    <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                      Infraestrutura de compliance
                    </p>
                    <div className="space-y-2">
                      {[
                        { label: "Audit trail assinado (HMAC)", ok: signed },
                        { label: "Hash chaining no audit log", ok: chainEnabled },
                        { label: "Multi-turn context ativo", ok: multiTurn },
                        { label: "Budget cap configurado", ok: budgetCap },
                        { label: `Retenção de dados (${ttlDays}d)`, ok: ttlDays >= 365 },
                      ].map((item) => (
                        <div key={item.label} className="flex items-center justify-between text-sm">
                          <span className="text-[var(--color-text-muted)]">{item.label}</span>
                          <span className={`text-xs font-medium ${item.ok ? "text-green-400" : "text-amber-400"}`}>
                            {item.ok ? "✓ ativo" : "⚠ inativo"}
                          </span>
                        </div>
                      ))}
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-[var(--color-text-muted)]">Residência de dados</span>
                        <span className="text-xs font-medium text-[var(--color-text)]">{dataResidency}</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Report signature */}
                {sig && (
                  <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                    <p className="mb-1.5 text-xs font-medium text-[var(--color-text-muted)]">
                      Assinatura HMAC deste relatório
                    </p>
                    <code className="block break-all text-xs text-teal-400">{sig}</code>
                    <p className="mt-1.5 text-xs text-[var(--color-text-muted)]">
                      Verifique com HMAC-SHA256 usando <code>AION_SESSION_AUDIT_SECRET</code>
                    </p>
                  </div>
                )}

                {/* Sessions audit info */}
                <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
                  <p className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                    Cobertura de audit trail
                  </p>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--color-text-muted)]">Sessões com trilha de auditoria</span>
                    <span className="font-semibold text-[var(--color-text)]">
                      {((audit.sessions_with_audit_trail as number) ?? 0).toLocaleString("pt-BR")}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-[var(--color-text-muted)]">
                    Cada sessão inclui: hash da mensagem (LGPD), decisão tomada, modelo usado, PIIs detectados, políticas aplicadas.
                  </p>
                </div>
              </div>
            );
          })()}

          {/* LGPD Danger Zone */}
          <div className="rounded-xl border border-red-800/50 bg-red-950/20 p-5">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-red-400">
                  <Trash2 className="h-4 w-4" />
                  Exclusão de dados — LGPD Art. 18
                </h3>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  Remove todos os dados deste tenant: sessões, audit trail, memória operacional, budget.
                  Ação irreversível. Use apenas em atendimento a solicitação formal de titular de dados.
                </p>
              </div>
              <button
                onClick={() => { setShowLgpdModal(true); setDeleteError(null); setLgpdConfirmText(""); setLgpdReason(""); }}
                className="flex-shrink-0 ml-4 flex items-center gap-1.5 rounded-lg border border-red-800/60 bg-red-950/40 px-3 py-2 text-xs font-medium text-red-400 hover:bg-red-900/30 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Excluir dados
              </button>
            </div>
          </div>
        </div>
      )}

      {/* LGPD Deletion Modal */}
      {showLgpdModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-red-800/50 bg-[var(--color-surface)] p-8 shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-900/30 text-red-400">
                <Trash2 className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-red-400">Exclusão irreversível de dados</h3>
                <p className="text-xs text-[var(--color-text-muted)]">LGPD Art. 18 — Direito à exclusão</p>
              </div>
            </div>

            <div className="space-y-2 rounded-lg bg-red-950/30 p-4 text-xs text-[var(--color-text-muted)] mb-4">
              <p className="flex items-start gap-2"><span className="text-red-400 mt-0.5">●</span> Todas as sessões e audit trail serão excluídos</p>
              <p className="flex items-start gap-2"><span className="text-red-400 mt-0.5">●</span> Memória operacional (modelos aprendidos) será zerada</p>
              <p className="flex items-start gap-2"><span className="text-red-400 mt-0.5">●</span> Configurações de budget e calibração serão removidas</p>
              <p className="flex items-start gap-2"><span className="text-red-400 mt-0.5">●</span> Esta ação <strong className="text-red-400">não pode ser desfeita</strong></p>
            </div>

            <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">
              Digite <code className="text-red-400">excluir</code> para confirmar
            </label>
            <input
              type="text"
              value={lgpdConfirmText}
              onChange={(e) => setLgpdConfirmText(e.target.value)}
              placeholder="excluir"
              className="w-full rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-red-500 focus:outline-none"
            />

            <div className="mt-4 space-y-1.5">
              <label
                htmlFor="lgpd-reason"
                className="block text-xs text-[var(--color-text-muted)]"
              >
                Motivo da exclusão{" "}
                <span className="opacity-60">(mín. 10 caracteres — obrigatório)</span>
              </label>
              <textarea
                id="lgpd-reason"
                value={lgpdReason}
                onChange={(e) => setLgpdReason(e.target.value)}
                rows={3}
                disabled={deleting}
                placeholder="Ex: Solicitação formal do titular de dados — protocolo #12345..."
                className="w-full resize-none rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]/50 focus:border-red-500 focus:outline-none disabled:opacity-50"
              />
              {lgpdReason.trim().length > 0 && lgpdReason.trim().length < 10 && (
                <p className="text-[10px] text-amber-400">
                  {lgpdReason.trim().length}/10 caracteres mínimos
                </p>
              )}
            </div>

            {deleteError && (
              <div className="mt-3 rounded-lg bg-red-950/50 px-3 py-2 text-xs text-red-400">
                {deleteError}
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => { setShowLgpdModal(false); setLgpdConfirmText(""); setLgpdReason(""); setDeleteError(null); }}
                disabled={deleting}
                className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                onClick={handleLgpdDelete}
                disabled={deleting || lgpdConfirmText.trim().toLowerCase() !== "excluir" || lgpdReason.trim().length < 10}
                className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {deleting ? "Excluindo..." : "Excluir todos os dados"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal */}
      {showConfirm && selectedAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-[var(--color-surface)] p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-[var(--color-text)]">
              {getConfirmTitle()}
            </h3>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">
              {getConfirmDescription()}
            </p>

            {/* Impact summary */}
            <div className="mt-4 space-y-2 rounded-lg bg-white/5 p-4 text-sm">
              {getImpactPoints().map((point, idx) => (
                <div key={idx} className="flex items-start gap-2">
                  <span className="mt-1 inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-primary)]" />
                  <span className="text-[var(--color-text-muted)]">{point}</span>
                </div>
              ))}
            </div>

            {selectedAction === "rotate-keys" && (
              <div className="mt-4 space-y-1.5">
                <label
                  htmlFor="admin-rotate-reason"
                  className="block text-xs font-medium text-[var(--color-text-muted)]"
                >
                  Motivo da rotação{" "}
                  <span className="opacity-60">(mín. 10 caracteres — obrigatório)</span>
                </label>
                <textarea
                  id="admin-rotate-reason"
                  value={rotateReason}
                  onChange={(e) => setRotateReason(e.target.value)}
                  rows={3}
                  disabled={saving}
                  placeholder="Descreva o motivo da rotação para o audit log..."
                  className="w-full resize-none rounded-lg border border-[var(--color-border)] bg-white/5 px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]/40 focus:border-[var(--color-primary)]/60 focus:outline-none transition-colors disabled:opacity-50"
                />
                {rotateReason.trim().length > 0 && rotateReason.trim().length < 10 && (
                  <p className="text-[10px] text-amber-400">
                    {rotateReason.trim().length}/10 caracteres mínimos
                  </p>
                )}
              </div>
            )}

            {saveError && (
              <div className="mt-3 rounded-lg bg-red-950/50 px-3 py-2 text-xs text-red-400">
                {saveError}
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={handleCancel}
                disabled={saving}
                className="cursor-pointer rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                onClick={handleConfirm}
                disabled={saving || (selectedAction === "rotate-keys" && rotateReason.trim().length < 10)}
                className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {saving ? "Processando..." : getActionButtonLabel()}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
