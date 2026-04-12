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
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { mockEvents } from "@/lib/mock-data";
import type { AionEvent } from "@/lib/types";

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

export function OperationsPage() {
  const [filter, setFilter] = useState<FilterType>("all");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState<AionEvent | null>(null);

  const filtered = filter === "all"
    ? mockEvents
    : mockEvents.filter((e) => {
        if (filter === "error") return e.decision === "error" || e.error;
        return e.decision === filter;
      });

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  return (
    <div className="space-y-6">
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
          <button className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-text)]">
            <Download className="h-3.5 w-3.5" />
            Exportar
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
          <table className="w-full min-w-[800px]">
            <thead>
              <tr className="border-b border-[var(--color-border)] bg-white/5 text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
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
                return (
                  <tr
                    key={evt.id}
                    onClick={() => setSelectedEvent(evt)}
                    className="cursor-pointer border-b border-[var(--color-border)] transition-colors last:border-0 hover:bg-[var(--color-primary)]/5"
                  >
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
                      ESTIXE
                    </span>
                    <ArrowRight className="h-3 w-3 text-[var(--color-text-muted)]" />
                    {selectedEvent.decision !== "bypass" && selectedEvent.decision !== "block" ? (
                      <>
                        <span className={`rounded border px-2 py-1 text-xs font-bold ${moduleColor("NOMOS")}`}>
                          NOMOS
                        </span>
                        <ArrowRight className="h-3 w-3 text-[var(--color-text-muted)]" />
                        <span className={`rounded border px-2 py-1 text-xs font-bold ${moduleColor("METIS")}`}>
                          METIS
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
    </div>
  );
}
