"use client";

import { useState } from "react";
import { Users, Shield, Key, RefreshCw, CheckCircle2, AlertCircle, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { mockAdminRoles, mockIdentityProviders } from "@/lib/mock-data";
import { rotateKeys } from "@/lib/api";

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

const tabs = ["Papéis & Permissões", "Provedores de Identidade", "Segurança de Acesso"] as const;
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

  const handleOpenConfirm = (actionType: AdminActionType, roleName?: string, idpName?: string) => {
    setSelectedAction(actionType);
    if (roleName) setSelectedRoleName(roleName);
    if (idpName) setSelectedIdPName(idpName);
    setSaveError(null);
    setShowConfirm(true);
  };

  const handleConfirm = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      if (selectedAction === "rotate-keys") {
        await rotateKeys([]);
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
                disabled={saving}
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
