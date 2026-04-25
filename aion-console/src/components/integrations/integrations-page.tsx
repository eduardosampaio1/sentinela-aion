"use client";

import { useState } from "react";
import { Plug, CheckCircle2, AlertCircle, Clock, Zap, Eye, Bell, Shield } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { mockIntegrations } from "@/lib/mock-data";
import type { Integration } from "@/lib/types";

const categoryConfig: Record<Integration["category"], { label: string; icon: React.ReactNode; color: string }> = {
  llm: { label: "LLM", icon: <Zap className="h-3.5 w-3.5" />, color: "text-sky-400" },
  observability: { label: "Observabilidade", icon: <Eye className="h-3.5 w-3.5" />, color: "text-violet-400" },
  notification: { label: "Notificação", icon: <Bell className="h-3.5 w-3.5" />, color: "text-amber-400" },
  security: { label: "Segurança", icon: <Shield className="h-3.5 w-3.5" />, color: "text-teal-400" },
};

const statusConfig: Record<Integration["status"], { icon: React.ReactNode; badge: "success" | "info" | "warning" | "error"; label: string }> = {
  connected: { icon: <CheckCircle2 className="h-4 w-4 text-green-400" />, badge: "success", label: "Conectado" },
  ready: { icon: <Clock className="h-4 w-4 text-sky-400" />, badge: "info", label: "Pronto" },
  pending: { icon: <Clock className="h-4 w-4 text-amber-400" />, badge: "warning", label: "Pendente" },
  error: { icon: <AlertCircle className="h-4 w-4 text-red-400" />, badge: "error", label: "Erro" },
};

type CategoryFilter = "all" | Integration["category"];

const filters: { id: CategoryFilter; label: string }[] = [
  { id: "all", label: "Todas" },
  { id: "llm", label: "LLM" },
  { id: "observability", label: "Observabilidade" },
  { id: "notification", label: "Notificação" },
  { id: "security", label: "Segurança" },
];

function IntegrationCard({
  integration,
  onAction
}: {
  integration: Integration;
  onAction: (integration: Integration, action: "connect" | "configure") => void;
}) {
  const cat = categoryConfig[integration.category];
  const status = statusConfig[integration.status];

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 hover:border-[var(--color-primary)]/40 transition-colors">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          {status.icon}
          <div>
            <p className="text-sm font-semibold text-[var(--color-text)]">{integration.name}</p>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">{integration.description}</p>
          </div>
        </div>
        <Badge variant={status.badge}>{status.label}</Badge>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <div className={`flex items-center gap-1.5 text-xs ${cat.color}`}>
          {cat.icon}
          {cat.label}
        </div>
        <div className="flex items-center gap-3">
          {integration.latency_ms !== null && (
            <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
              {integration.latency_ms}ms
            </span>
          )}
          <button
            onClick={() => onAction(integration, integration.status === "connected" ? "configure" : "connect")}
            className={`text-xs transition-colors ${
              integration.status === "connected"
                ? "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                : "text-[var(--color-primary)] hover:underline"
            }`}>
            {integration.status === "connected" ? "Configurar" : "Conectar"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function IntegrationsPage() {
  const [filter, setFilter] = useState<CategoryFilter>("all");
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null);
  const [action, setAction] = useState<"connect" | "configure" | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const filtered = filter === "all"
    ? mockIntegrations
    : mockIntegrations.filter((i) => i.category === filter);

  const connectedCount = mockIntegrations.filter((i) => i.status === "connected").length;
  const errorCount = mockIntegrations.filter((i) => i.status === "error").length;

  const handleAction = (integration: Integration, actionType: "connect" | "configure") => {
    setSelectedIntegration(integration);
    setAction(actionType);
    setSaveError(null);
    setShowConfirm(true);
  };

  const handleConfirm = async () => {
    if (!selectedIntegration || !action) return;

    setSaving(true);
    setSaveError(null);
    try {
      // Simular chamada API
      await new Promise(resolve => setTimeout(resolve, 1000));
      setShowConfirm(false);
      setSaving(false);
      // Em produção: chamar API para conectar ou configurar a integração
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Erro ao processar integração");
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setShowConfirm(false);
    setSaveError(null);
    setSelectedIntegration(null);
    setAction(null);
  };

  const getActionDescription = () => {
    if (!selectedIntegration || !action) return "";

    if (action === "connect") {
      return `Conectar ${selectedIntegration.name} ao AION será ativar a integração com as credenciais fornecidas. A validação acontecerá automaticamente.`;
    } else {
      return `Configurar ${selectedIntegration.name} permitirá ajustar seus parâmetros de funcionamento. As alterações serão aplicadas imediatamente a novas requisições.`;
    }
  };

  const getImpactPoints = () => {
    if (!selectedIntegration) return [];

    const impacts: string[] = [];

    if (action === "connect") {
      impacts.push("Credenciais serão validadas automaticamente");
      if (selectedIntegration.category === "llm") {
        impacts.push("Modelos disponíveis serão adicionados ao roteamento");
      } else if (selectedIntegration.category === "observability") {
        impacts.push("Métricas começarão a ser coletadas em tempo real");
      } else if (selectedIntegration.category === "notification") {
        impacts.push("Canais de notificação estarão disponíveis imediatamente");
      } else if (selectedIntegration.category === "security") {
        impacts.push("Políticas de segurança adicional serão aplicadas");
      }
    } else {
      impacts.push("Configurações serão aplicadas a partir da próxima requisição");
      impacts.push("Nenhum interrupção de serviço esperada");
      if (selectedIntegration.category === "llm") {
        impacts.push("Preferências de modelo serão atualizadas");
      }
    }

    return impacts;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            Integrações
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Provedores LLM, observabilidade, notificações e segurança
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="flex items-center gap-1.5 text-green-400">
            <CheckCircle2 className="h-4 w-4" />
            {connectedCount} conectadas
          </span>
          {errorCount > 0 && (
            <span className="flex items-center gap-1.5 text-red-400">
              <AlertCircle className="h-4 w-4" />
              {errorCount} com erro
            </span>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {filters.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === f.id
                ? "bg-[var(--color-primary)]/20 text-[var(--color-primary)]"
                : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)]"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {errorCount > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-red-800/40 bg-red-900/10 px-5 py-3">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
          <p className="text-sm text-red-300">
            {errorCount} integração com erro de conectividade. Verifique as credenciais.
          </p>
        </div>
      )}

      {/* Cards grid */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((integration) => (
          <IntegrationCard key={integration.name} integration={integration} onAction={handleAction} />
        ))}
      </div>

      {/* Integration Action Confirmation Modal */}
      {showConfirm && selectedIntegration && action && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-[var(--color-surface)] p-8 shadow-xl">
            <h3 className="text-lg font-semibold text-[var(--color-text)]">
              {action === "connect" ? "Conectar integração?" : "Configurar integração?"}
            </h3>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">
              {getActionDescription()}
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
                {saving ? (action === "connect" ? "Conectando..." : "Configurando...") : (action === "connect" ? "Conectar" : "Configurar")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
