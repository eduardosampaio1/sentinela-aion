"use client";

import { useState } from "react";
import {
  RefreshCw,
  Download,
  X,
  Activity,
  GitBranch,
  Shield,
  Gauge,
  ArrowRight,
  AlertTriangle,
  Bell,
  BellOff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Toggle } from "@/components/ui/toggle";
import { TimeRangeSelect, timeRangeMs } from "@/components/ui/time-range-select";
import type { TimeRange } from "@/components/ui/time-range-select";
import { ConfirmActionModal } from "@/components/ui/confirm-action-modal";
import { useAionData } from "@/lib/use-aion-data";
import { DemoBanner } from "@/components/ui/demo-banner";
import { mockEvents, mockMonitors } from "@/lib/mock-data";
import type { AionEvent, Monitor } from "@/lib/types";
import { toggleModule } from "@/lib/api";

type FilterType = "all" | "bypass" | "route" | "block" | "error";

const filterConfig: { id: FilterType; label: string }[] = [
  { id: "all", label: "Todas" },
  { id: "bypass", label: "Desviadas" },
  { id: "route", label: "Roteadas" },
  { id: "block", label: "Bloqueadas" },
  { id: "error", label: "Com erro" },
];

const moduleIcon = (module: string | null) => {
  switch (module) {
    case "ESTIXE": return <Shield className="h-3.5 w-3.5 text-teal-600" />;
    case "NOMOS": return <GitBranch className="h-3.5 w-3.5 text-sky-600" />;
    case "METIS": return <Gauge className="h-3.5 w-3.5 text-violet-600" />;
    default: return null;
  }
};

const moduleColor = (module: string | null) => {
  switch (module) {
    case "ESTIXE": return "bg-teal-900/30 text-teal-400 border-teal-800/50";
    case "NOMOS": return "bg-sky-900/30 text-sky-400 border-sky-800/50";
    case "METIS": return "bg-violet-900/30 text-violet-400 border-violet-800/50";
    default: return "bg-white/10 text-slate-400 border-slate-700";
  }
};

const decisionConfig: Record<string, { bg: string; text: string; label: string }> = {
  bypass: { bg: "bg-teal-900/30", text: "text-teal-400", label: "Desviado" },
  route: { bg: "bg-blue-900/30", text: "text-blue-400", label: "Roteado" },
  block: { bg: "bg-red-900/30", text: "text-red-400", label: "Bloqueado" },
  fallback: { bg: "bg-amber-900/30", text: "text-amber-400", label: "Fallback" },
  error: { bg: "bg-red-500", text: "text-white", label: "Erro" },
};

const latencyColor = (ms: number) => {
  if (ms < 500) return "text-green-600";
  if (ms < 2000) return "text-amber-600";
  return "text-red-600";
};

const MODULE_CONFIG = [
  {
    name: "estixe" as const,
    label: "Proteção",
    desc: "Classificação, desvio e bloqueio semântico",
    Icon: Shield,
    color: { ring: "border-teal-800/40", bg: "bg-teal-900/20", icon: "text-teal-400", badge: "text-teal-300" },
  },
  {
    name: "nomos" as const,
    label: "Roteamento",
    desc: "Inteligência adaptativa de roteamento",
    Icon: GitBranch,
    color: { ring: "border-sky-800/40", bg: "bg-sky-900/20", icon: "text-sky-400", badge: "text-sky-300" },
  },
  {
    name: "metis" as const,
    label: "Otimização",
    desc: "Compressão e otimização de contexto",
    Icon: Gauge,
    color: { ring: "border-violet-800/40", bg: "bg-violet-900/20", icon: "text-violet-400", badge: "text-violet-300" },
  },
] as const;

export function OperationsPage() {
  const [filter, setFilter] = useState<FilterType>("all");
  const [timeRange, setTimeRange] = useState<TimeRange>("1h");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState<AionEvent | null>(null);

  // Module toggles
  const [moduleEnabled, setModuleEnabled] = useState<Record<"estixe" | "nomos" | "metis", boolean>>({
    estixe: true, nomos: true, metis: true,
  });
  const [moduleToggling, setModuleToggling] = useState<string | null>(null);

  // Confirmation modal for module toggle
  const [pendingToggle, setPendingToggle] = useState<{
    name: "estixe" | "nomos" | "metis";
    enabled: boolean;
  } | null>(null);
  const [toggleConfirmLoading, setToggleConfirmLoading] = useState(false);
  const [toggleConfirmError, setToggleConfirmError] = useState<string | null>(null);

  // Intercept the toggle — open confirmation modal instead of calling API directly
  const handleModuleToggle = (name: "estixe" | "nomos" | "metis", enabled: boolean) => {
    setToggleConfirmError(null);
    setPendingToggle({ name, enabled });
  };

  const handleToggleConfirm = async (reason: string) => {
    if (!pendingToggle) return;
    const { name, enabled } = pendingToggle;
    setToggleConfirmLoading(true);
    setToggleConfirmError(null);
    try {
      await toggleModule(name, enabled, reason);
      setModuleEnabled((s) => ({ ...s, [name]: enabled }));
      setPendingToggle(null);
    } catch (err) {
      setToggleConfirmError(err instanceof Error ? err.message : "Erro ao alterar módulo");
    } finally {
      setToggleConfirmLoading(false);
      setModuleToggling(null);
    }
  };

  const liveData = useAionData(3000, autoRefresh);
  const events = liveData.connected && liveData.events.length > 0
    ? liveData.events
    : mockEvents;

  const cutoff = Date.now() - timeRangeMs(timeRange);
  const inRange = timeRange === "live"
    ? events
    : events.filter((e) => new Date(e.timestamp).getTime() >= cutoff);

  const filtered = (filter === "all" ? inRange : inRange.filter((e) => {
    if (filter === "error") return e.decision === "error" || e.error;
    return e.decision === filter;
  }));

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  return (
    <div className="space-y-6">
      {/* Demo banner when backend is unreachable */}
      {!liveData.connected && (
        <DemoBanner onRetry={() => setAutoRefresh(true)} />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            Operação
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Cada decisão mostra qual módulo agiu e por quê.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              autoRefresh
                ? "border-[var(--color-primary)] bg-[var(--color-primary)]/5 text-[var(--color-primary)]"
                : "border-[var(--color-border)] text-[var(--color-text-muted)]"
            }`}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${autoRefresh ? "animate-spin" : ""}`} style={autoRefresh ? { animationDuration: "3s" } : undefined} />
            {autoRefresh ? "Ao vivo" : "Manual"}
          </button>
          <TimeRangeSelect value={timeRange} onChange={setTimeRange} />
          <button
            onClick={() => {
              const header = "timestamp,module,input,decision,model,response_time_ms,cost\n";
              const rows = filtered.map((e) =>
                `"${e.timestamp}","${e.module || ""}","${(e.input || "").replace(/"/g, '""')}","${e.decision}","${e.model_used || ""}",${e.response_time_ms},${e.cost ?? 0}`
              ).join("\n");
              const blob = new Blob([header + rows], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `aion-events-${new Date().toISOString().slice(0, 10)}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }}
            className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-text)]"
          >
            <Download className="h-3.5 w-3.5" />
            Exportar CSV
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {filterConfig.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`cursor-pointer rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === f.id
                ? "bg-[var(--color-primary)] text-white"
                : "bg-slate-100 text-[var(--color-text-muted)] hover:bg-slate-200"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* ═══ Módulos ═══ */}
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Módulos ativos
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {MODULE_CONFIG.map((mod) => {
            const enabled = moduleEnabled[mod.name];
            const toggling = pendingToggle?.name === mod.name && toggleConfirmLoading;
            const Icon = mod.Icon;
            return (
              <div
                key={mod.name}
                className={`flex items-center justify-between rounded-xl border p-4 transition-all ${
                  enabled
                    ? `${mod.color.ring} ${mod.color.bg}`
                    : "border-slate-700/40 bg-white/[0.02] opacity-60"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/5`}>
                    <Icon className={`h-4 w-4 ${enabled ? mod.color.icon : "text-[var(--color-text-muted)]"}`} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-bold ${enabled ? mod.color.badge : "text-[var(--color-text-muted)]"}`}>
                        {mod.label}
                      </span>
                      {!enabled && (
                        <Badge variant="muted">Desligado</Badge>
                      )}
                    </div>
                    <p className="text-[11px] text-[var(--color-text-muted)]">{mod.desc}</p>
                  </div>
                </div>
                <Toggle
                  enabled={enabled}
                  onChange={(v) => handleModuleToggle(mod.name, v)}
                  label={mod.label}
                  disabled={toggling || !!pendingToggle}
                />
              </div>
            );
          })}
        </div>
      </section>

      {/* Monitores */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-[family-name:var(--font-heading)] text-lg font-semibold text-[var(--color-text)]">
              Monitores
            </h2>
            <p className="text-xs text-[var(--color-text-muted)]">
              Alertas contínuos sobre métricas críticas do pipeline — últimas 24 horas.
            </p>
          </div>
          <div className="relative group">
            <button
              disabled
              className="flex cursor-not-allowed items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] opacity-50"
            >
              <Bell className="h-3.5 w-3.5" />
              + Novo monitor
            </button>
            <span className="pointer-events-none absolute right-0 top-full mt-1.5 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-[10px] text-slate-300 opacity-0 transition-opacity group-hover:opacity-100">
              Em breve
            </span>
          </div>
        </div>

        {/* When connected to backend, monitors require GET /v1/monitors/{tenant} (roadmap T1.x).
            Show a placeholder rather than fake data. In demo mode, display mock monitors. */}
        {liveData.connected ? (
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-8 text-center">
            <p className="text-sm font-medium text-[var(--color-text-muted)]">
              Monitores em tempo real requerem o endpoint{" "}
              <code className="rounded bg-white/5 px-1 py-0.5 text-xs">GET /v1/monitors/{"{tenant}"}</code>
              {" "}(em desenvolvimento — roadmap T1.x).
            </p>
          </div>
        ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {mockMonitors.map((monitor: Monitor) => {
            const isOk = monitor.status === "ok";
            const isTriggered = monitor.status === "triggered";
            const isNoData = monitor.status === "no_data";

            const dotClass = isOk
              ? "bg-green-400"
              : isTriggered
              ? "bg-red-400 animate-pulse"
              : "bg-slate-500";

            const valueClass = isOk
              ? "text-green-400"
              : isTriggered
              ? "text-red-400"
              : "text-[var(--color-text-muted)]";

            const slotClass = (s: "ok" | "triggered" | "no_data") =>
              s === "ok"
                ? "bg-green-500/60"
                : s === "triggered"
                ? "bg-red-500/70"
                : "bg-slate-700/50";

            const thresholdLabel =
              monitor.threshold_direction === "above"
                ? `Alerta quando > ${monitor.threshold}${monitor.unit}`
                : `Alerta quando < ${monitor.threshold}${monitor.unit}`;

            const formatLastTriggered = (iso: string) => {
              const d = new Date(iso);
              const dd = String(d.getDate()).padStart(2, "0");
              const mm = String(d.getMonth() + 1).padStart(2, "0");
              const hh = String(d.getHours()).padStart(2, "0");
              const min = String(d.getMinutes()).padStart(2, "0");
              return `${dd}/${mm} ${hh}:${min}`;
            };

            return (
              <div
                key={monitor.id}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 space-y-2"
              >
                {/* Top row */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`h-2 w-2 flex-shrink-0 rounded-full ${dotClass}`} />
                    <span className="truncate text-xs font-semibold text-[var(--color-text)]">
                      {monitor.name}
                    </span>
                  </div>
                  <div className="flex-shrink-0 text-right">
                    <span className={`font-[family-name:var(--font-mono)] text-sm font-bold ${valueClass}`}>
                      {monitor.current_value.toLocaleString("pt-BR")}{monitor.unit}
                    </span>
                  </div>
                </div>

                {/* Threshold context */}
                <p className="text-[10px] text-[var(--color-text-muted)]">{thresholdLabel}</p>

                {/* Description */}
                <p className="text-[10px] text-[var(--color-text-muted)] leading-relaxed">
                  {monitor.description}
                </p>

                {/* Alert history timeline */}
                <div className="flex gap-[2px] items-end">
                  {monitor.alert_history.map((slot, i) => {
                    const isLast = i === monitor.alert_history.length - 1;
                    return (
                      <span
                        key={slot.hour}
                        className={`flex-1 rounded-[2px] ${slotClass(slot.status)} ${isLast ? "brightness-125" : ""}`}
                        style={{ height: isLast ? "10px" : "6px" }}
                        title={`h${slot.hour}: ${slot.status}`}
                      />
                    );
                  })}
                </div>

                {/* Triggered warning */}
                {isTriggered && monitor.last_triggered && (
                  <div className="flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-1">
                    <AlertTriangle className="h-3 w-3 flex-shrink-0 text-amber-400" />
                    <span className="text-[10px] font-medium text-amber-400">
                      Disparado em {formatLastTriggered(monitor.last_triggered)}
                    </span>
                  </div>
                )}

                {isNoData && (
                  <div className="flex items-center gap-1 rounded-md bg-slate-700/30 px-2 py-1">
                    <BellOff className="h-3 w-3 flex-shrink-0 text-[var(--color-text-muted)]" />
                    <span className="text-[10px] text-[var(--color-text-muted)]">Sem dados</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        )}
      </section>

      {/* Events Table */}
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-x-auto">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Activity className="mb-3 h-10 w-10 text-[var(--color-text-muted)]" />
            <h3 className="text-sm font-semibold text-[var(--color-text)]">Nenhuma operação registrada</h3>
            <p className="mt-1 max-w-sm text-xs text-[var(--color-text-muted)]">
              Quando o AION processar requisições, as decisões aparecerão aqui em tempo real.
            </p>
          </div>
        ) : (
          <table className="w-full min-w-[900px]">
            <thead>
              <tr className="border-b border-[var(--color-border)] bg-white/5 text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                <th className="px-4 py-3">Sessão</th>
                <th className="px-4 py-3">Quando</th>
                <th className="px-4 py-3">Módulo</th>
                <th className="px-4 py-3">Entrada</th>
                <th className="px-4 py-3">Decisão</th>
                <th className="px-4 py-3">Modelo</th>
                <th className="px-4 py-3 text-right">Tempo</th>
                <th className="px-4 py-3 text-right">Custo</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((evt) => {
                const dc = decisionConfig[evt.decision] || decisionConfig.error;
                const sessionId = `sess_${evt.id.slice(-4)}`;
                return (
                  <tr
                    key={evt.id}
                    onClick={() => setSelectedEvent(evt)}
                    className="cursor-pointer border-b border-[var(--color-border)] transition-colors last:border-0 hover:bg-[var(--color-primary)]/5"
                  >
                    <td className="whitespace-nowrap px-4 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-primary)]">
                      {sessionId}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                      {formatTime(evt.timestamp)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[10px] font-bold ${moduleColor(evt.module)}`}>
                        {moduleIcon(evt.module)}
                        {evt.module || "—"}
                      </span>
                    </td>
                    <td className="max-w-xs truncate px-4 py-3 text-sm text-[var(--color-text)]">
                      {evt.input}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${dc.bg} ${dc.text}`}>
                        {dc.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                      {evt.model_used || "—"}
                    </td>
                    <td className={`whitespace-nowrap px-4 py-3 text-right font-[family-name:var(--font-mono)] text-xs font-medium ${latencyColor(evt.response_time_ms)}`}>
                      {evt.response_time_ms}ms
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-[family-name:var(--font-mono)] text-xs text-[var(--color-text-muted)]">
                      {evt.cost ? `$${evt.cost.toFixed(4)}` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Detail Modal */}
      {selectedEvent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="w-full max-w-2xl rounded-2xl bg-[var(--color-surface)] shadow-xl">
            <div className="flex items-center justify-between border-b border-[var(--color-border)] px-6 py-4">
              <div className="flex items-center gap-3">
                <h3 className="text-lg font-semibold text-[var(--color-text)]">Detalhes da decisão</h3>
                <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-xs font-bold ${moduleColor(selectedEvent.module)}`}>
                  {moduleIcon(selectedEvent.module)}
                  {selectedEvent.module}
                </span>
              </div>
              <button onClick={() => setSelectedEvent(null)} className="cursor-pointer text-[var(--color-text-muted)] hover:text-[var(--color-text)]" aria-label="Fechar">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="max-h-[70vh] overflow-y-auto p-6">
              <div className="space-y-5">
                {/* Decision Path */}
                <div>
                  <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Caminho da decisão</label>
                  <div className="mt-2 flex items-center gap-2">
                    <span className="rounded bg-slate-100 px-2 py-1 text-xs font-medium text-[var(--color-text)]">Input</span>
                    <ArrowRight className="h-3 w-3 text-[var(--color-text-muted)]" />
                    <span className={`rounded border px-2 py-1 text-xs font-bold ${moduleColor("ESTIXE")}`}>
                      Proteção
                    </span>
                    <ArrowRight className="h-3 w-3 text-[var(--color-text-muted)]" />
                    {selectedEvent.decision !== "bypass" && selectedEvent.decision !== "block" ? (
                      <>
                        <span className={`rounded border px-2 py-1 text-xs font-bold ${moduleColor("NOMOS")}`}>
                          Roteamento
                        </span>
                        <ArrowRight className="h-3 w-3 text-[var(--color-text-muted)]" />
                        <span className={`rounded border px-2 py-1 text-xs font-bold ${moduleColor("METIS")}`}>
                          Otimização
                        </span>
                        <ArrowRight className="h-3 w-3 text-[var(--color-text-muted)]" />
                      </>
                    ) : null}
                    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${decisionConfig[selectedEvent.decision]?.bg} ${decisionConfig[selectedEvent.decision]?.text}`}>
                      {decisionConfig[selectedEvent.decision]?.label}
                    </span>
                  </div>
                </div>

                <div>
                  <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Entrada do usuário</label>
                  <p className="mt-1 rounded-lg bg-white/5 p-3 text-sm text-[var(--color-text)]">{selectedEvent.input}</p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Módulo responsável</label>
                    <div className="mt-1 flex items-center gap-1.5">
                      {moduleIcon(selectedEvent.module)}
                      <span className="font-[family-name:var(--font-mono)] text-sm font-bold text-[var(--color-text)]">{selectedEvent.module}</span>
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Modelo</label>
                    <p className="mt-1 font-[family-name:var(--font-mono)] text-sm text-[var(--color-text)]">
                      {selectedEvent.model_used || "Nenhum (desviado)"}
                    </p>
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Tempo de resposta</label>
                    <p className={`mt-1 font-[family-name:var(--font-mono)] text-sm font-medium ${latencyColor(selectedEvent.response_time_ms)}`}>
                      {selectedEvent.response_time_ms}ms
                    </p>
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Custo</label>
                    <p className="mt-1 font-[family-name:var(--font-mono)] text-sm text-[var(--color-text)]">
                      {selectedEvent.cost ? `$${selectedEvent.cost.toFixed(4)}` : "R$ 0,00 (desviado)"}
                    </p>
                  </div>
                  {selectedEvent.tokens_used && (
                    <div>
                      <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Tokens</label>
                      <p className="mt-1 font-[family-name:var(--font-mono)] text-sm text-[var(--color-text)]">
                        {selectedEvent.tokens_used.toLocaleString("pt-BR")}
                      </p>
                    </div>
                  )}
                  {selectedEvent.policy_applied && (
                    <div>
                      <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Política aplicada</label>
                      <p className="mt-1 font-[family-name:var(--font-mono)] text-sm text-[var(--color-text)]">
                        {selectedEvent.policy_applied}
                      </p>
                    </div>
                  )}
                </div>

                {selectedEvent.output && (
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Resposta gerada</label>
                    <p className="mt-1 rounded-lg bg-white/5 p-3 text-sm text-[var(--color-text)]">{selectedEvent.output}</p>
                  </div>
                )}

                {selectedEvent.error && (
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wider text-red-500">Erro</label>
                    <p className="mt-1 rounded-lg bg-red-950/50 p-3 text-sm text-red-400">{selectedEvent.error}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Confirm modal for module toggle ── */}
      {pendingToggle && (
        <ConfirmActionModal
          open
          severity="warning"
          title={`${pendingToggle.enabled ? "Ativar" : "Desativar"} módulo ${pendingToggle.name.toUpperCase()}?`}
          description={
            pendingToggle.enabled
              ? `O módulo ${pendingToggle.name.toUpperCase()} será reativado e voltará a processar requisições em produção.`
              : `O módulo ${pendingToggle.name.toUpperCase()} será desativado. Requisições continuarão fluindo sem este módulo até que seja reativado.`
          }
          impact={
            pendingToggle.enabled
              ? [
                  `• ${pendingToggle.name.toUpperCase()} voltará a processar todo o tráfego imediatamente`,
                  "• Nenhuma interrupção de tráfego — mudança gradual",
                ]
              : [
                  `• ${pendingToggle.name.toUpperCase()} não processará mais requisições`,
                  "• Tráfego continuará fluindo, mas sem as proteções/otimizações deste módulo",
                  "• A mudança tem efeito imediato em produção",
                ]
          }
          actionLabel={pendingToggle.enabled ? "Ativar módulo" : "Desativar módulo"}
          loading={toggleConfirmLoading}
          error={toggleConfirmError}
          onConfirm={handleToggleConfirm}
          onCancel={() => setPendingToggle(null)}
        />
      )}
    </div>
  );
}
