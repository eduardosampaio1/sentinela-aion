"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getHealth, type HealthInfo } from "@/lib/api/observability";

// ─── Canvas dimensions (SVG viewBox) ──────────────────────────────────────────
const W = 980;
const H = 460;

// ─── Bezier path helper ────────────────────────────────────────────────────────
function bp(x1: number, y1: number, x2: number, y2: number) {
  const mx = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
}

// ─── Mode metadata ─────────────────────────────────────────────────────────────
const MODE_LABELS: Record<string, string> = {
  poc_decision:    "POC Decision-Only",
  poc_transparent: "POC Transparente",
  full_transparent: "Transparente",
  decision_only:   "Decision-Only",
  not_configured:  "Modo não configurado",
};

const MODE_DESCRIPTIONS: Record<string, string> = {
  poc_decision:    "AION decide e devolve a decisão. O cliente faz a chamada ao LLM.",
  poc_transparent: "AION decide, encaminha ao LLM e devolve a resposta ao cliente.",
  full_transparent: "AION decide, encaminha ao LLM e devolve a resposta ao cliente.",
  decision_only:   "AION decide e devolve a decisão. O cliente faz a chamada ao LLM.",
  not_configured:  "Aguardando o backend reportar o modo de operação.",
};

const MODE_COLORS: Record<string, { dot: string; text: string; bg: string; ring: string }> = {
  poc_decision:    { dot: "bg-amber-400",   text: "text-amber-300",   bg: "bg-amber-500/10",   ring: "ring-amber-500/30" },
  poc_transparent: { dot: "bg-sky-400",     text: "text-sky-300",     bg: "bg-sky-500/10",     ring: "ring-sky-500/30" },
  full_transparent:{ dot: "bg-emerald-400", text: "text-emerald-300", bg: "bg-emerald-500/10", ring: "ring-emerald-500/30" },
  decision_only:   { dot: "bg-violet-400",  text: "text-violet-300",  bg: "bg-violet-500/10",  ring: "ring-violet-500/30" },
  not_configured:  { dot: "bg-slate-500",   text: "text-slate-400",   bg: "bg-white/5",        ring: "ring-white/10" },
};

// ─── Types ─────────────────────────────────────────────────────────────────────
type NodeType = "client" | "entry" | "module" | "output" | "model";

type NodeDef = {
  id: string;
  cx: number;
  cy: number;
  w: number;
  h: number;
  label: string;
  sublabel: string;
  accent: string;
  bg: string;
  textAccent: string;
  type: NodeType;
  /** Backend module id (for matching against `active_modules` from /health). */
  moduleId?: "estixe" | "nomos" | "metis";
  stats: Record<string, string>;
};

type EdgeDef = {
  fromId: string;
  toId: string;
  x1: number; y1: number;
  x2: number; y2: number;
  label?: string;
  dashed?: boolean;
  color: string;
  /** When true the edge represents the response leg (LLM → client / decision back to client). */
  isResponse?: boolean;
  /** Edge only renders in this deployment mode. Omit for "always shown". */
  modes?: ("poc_decision" | "poc_transparent" | "full_transparent" | "decision_only")[];
};

// ─── Node definitions ─────────────────────────────────────────────────────────
const NODES: NodeDef[] = [
  // 1. Client app — the calling application (NEW)
  {
    id: "client",
    cx: 56, cy: 230,
    w: 96, h: 56,
    label: "App Cliente",
    sublabel: "origem das chamadas",
    accent: "border-indigo-500/60",
    bg: "bg-indigo-950/40",
    textAccent: "text-indigo-300",
    type: "client",
    stats: {
      "Volume / dia": "22.840",
      "Pico": "1.200 req/h",
      "Integração": "OpenAI-compatible",
      "Auth": "Bearer Token",
    },
  },
  // 2. AION gateway — entry point inside AION
  {
    id: "entry",
    cx: 210, cy: 230,
    w: 92, h: 50,
    label: "AION Gateway",
    sublabel: "100% recebido",
    accent: "border-slate-600",
    bg: "bg-slate-800/70",
    textAccent: "text-slate-200",
    type: "entry",
    stats: {
      "Volume / dia": "22.840",
      "Pico": "1.200 req/h",
      "Latência entrada": "< 1ms",
      "TLS": "1.3",
    },
  },
  {
    id: "estixe",
    cx: 380, cy: 230,
    w: 140, h: 86,
    label: "Proteção",
    sublabel: "proteção & bypass",
    accent: "border-teal-600/70",
    bg: "bg-teal-950/50",
    textAccent: "text-teal-400",
    type: "module",
    moduleId: "estixe",
    stats: {
      "Decisões / dia": "22.840",
      "Bypass": "40%",
      "Bloqueios": "15%",
      "Para Roteamento": "45%",
      "Latência": "8ms",
    },
  },
  {
    id: "bypass",
    cx: 620, cy: 90,
    w: 144, h: 56,
    label: "⚡ Bypass",
    sublabel: "40% · custo zero",
    accent: "border-teal-500/60",
    bg: "bg-teal-900/30",
    textAccent: "text-teal-300",
    type: "output",
    stats: {
      "Req / dia": "9.136",
      "Custo": "US$ 0",
      "Latência": "8ms",
      "Economia / dia": "US$ 84",
    },
  },
  {
    id: "block",
    cx: 620, cy: 195,
    w: 144, h: 56,
    label: "🛡 Bloqueado",
    sublabel: "15% · custo zero",
    accent: "border-red-600/60",
    bg: "bg-red-950/40",
    textAccent: "text-red-400",
    type: "output",
    stats: {
      "Req / dia": "3.426",
      "Top ameaça": "Prompt injection",
      "2ª ameaça": "PII detection",
      "Políticas ativas": "6",
    },
  },
  {
    id: "nomos",
    cx: 620, cy: 340,
    w: 140, h: 86,
    label: "Roteamento",
    sublabel: "roteamento IA",
    accent: "border-sky-600/70",
    bg: "bg-sky-950/50",
    textAccent: "text-sky-400",
    type: "module",
    moduleId: "nomos",
    stats: {
      "Rotas / dia": "10.278",
      "Acurácia": "94%",
      "Latência": "18ms",
      "Economia / dia": "US$ 16",
    },
  },
  {
    id: "gpt4o",
    cx: 850, cy: 220,
    w: 140, h: 50,
    label: "gpt-4o",
    sublabel: "14% · $2.50/1M",
    accent: "border-violet-500/60",
    bg: "bg-violet-950/40",
    textAccent: "text-violet-400",
    type: "model",
    stats: {
      "Req / dia": "1.439",
      "Custo médio": "$0.0042",
      "Latência P50": "1.240ms",
      "Uso": "complexo",
    },
  },
  {
    id: "gpt4mini",
    cx: 850, cy: 290,
    w: 140, h: 50,
    label: "gpt-4o-mini",
    sublabel: "25% · $0.15/1M",
    accent: "border-sky-500/60",
    bg: "bg-sky-950/40",
    textAccent: "text-sky-400",
    type: "model",
    stats: {
      "Req / dia": "5.695",
      "Custo médio": "$0.0003",
      "Latência P50": "890ms",
      "Uso": "padrão",
    },
  },
  {
    id: "claude",
    cx: 850, cy: 360,
    w: 140, h: 50,
    label: "claude-sonnet",
    sublabel: "4% · $3.00/1M",
    accent: "border-amber-500/60",
    bg: "bg-amber-950/40",
    textAccent: "text-amber-400",
    type: "model",
    stats: {
      "Req / dia": "411",
      "Custo médio": "$0.0052",
      "Latência P50": "1.100ms",
      "Uso": "código",
    },
  },
  {
    id: "gemini",
    cx: 850, cy: 430,
    w: 140, h: 50,
    label: "gemini-flash",
    sublabel: "2% · $0.10/1M",
    accent: "border-green-600/50",
    bg: "bg-green-950/40",
    textAccent: "text-green-400",
    type: "model",
    stats: {
      "Req / dia": "206",
      "Custo médio": "$0.0001",
      "Latência P50": "720ms",
      "Uso": "fallback",
    },
  },
];

// ─── Edge definitions ──────────────────────────────────────────────────────────
const EDGES: EdgeDef[] = [
  // Client → AION Gateway (request)
  { fromId: "client", toId: "entry",   x1: 104, y1: 230, x2: 164, y2: 230, color: "#818cf8", label: "request" },
  // AION Gateway → Proteção
  { fromId: "entry", toId: "estixe",   x1: 256, y1: 230, x2: 310, y2: 230, color: "#475569" },
  // Proteção → Bypass
  { fromId: "estixe", toId: "bypass",  x1: 450, y1: 213, x2: 548, y2: 90,  color: "#2dd4bf", label: "40%" },
  // Proteção → Block
  { fromId: "estixe", toId: "block",   x1: 450, y1: 230, x2: 548, y2: 195, color: "#f87171", label: "15%", dashed: true },
  // Proteção → Roteamento
  { fromId: "estixe", toId: "nomos",   x1: 450, y1: 247, x2: 548, y2: 340, color: "#38bdf8", label: "45%" },
  // Roteamento → models
  { fromId: "nomos", toId: "gpt4o",    x1: 690, y1: 326, x2: 780, y2: 220, color: "#a78bfa", label: "14%" },
  { fromId: "nomos", toId: "gpt4mini", x1: 690, y1: 336, x2: 780, y2: 290, color: "#38bdf8", label: "25%" },
  { fromId: "nomos", toId: "claude",   x1: 690, y1: 348, x2: 780, y2: 360, color: "#fbbf24", label: "4%",  dashed: true },
  { fromId: "nomos", toId: "gemini",   x1: 690, y1: 358, x2: 780, y2: 430, color: "#4ade80", label: "2%",  dashed: true },

  // ── RESPONSE LEGS ──────────────────────────────────────────────────────────
  // In TRANSPARENT mode: response goes back through the AION gateway, then to the client.
  // We draw a single "merged" return arc from the right side of the topology back to the gateway,
  // and from gateway back to the client.
  {
    fromId: "gpt4mini", toId: "entry",
    x1: 780, y1: 305, x2: 256, y2: 245,
    color: "#10b981", isResponse: true,
    modes: ["poc_transparent", "full_transparent"],
  },
  {
    fromId: "entry", toId: "client",
    x1: 164, y1: 245, x2: 104, y2: 245,
    color: "#10b981", isResponse: true, label: "resposta",
    modes: ["poc_transparent", "full_transparent"],
  },
  // In DECISION-ONLY mode: AION returns the routing decision (no LLM call from AION's side).
  {
    fromId: "entry", toId: "client",
    x1: 164, y1: 245, x2: 104, y2: 245,
    color: "#fbbf24", isResponse: true, label: "decisão",
    dashed: true,
    modes: ["poc_decision", "decision_only"],
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────
function isModuleDisabled(node: NodeDef, activeModules: Set<string> | null): boolean {
  if (!node.moduleId) return false;
  // When we don't yet know the active set (loading or backend offline), assume all enabled.
  if (activeModules === null) return false;
  return !activeModules.has(node.moduleId);
}

function isEdgeForMode(edge: EdgeDef, mode: string): boolean {
  if (!edge.modes) return true;
  return (edge.modes as readonly string[]).includes(mode);
}

// ─── Component ────────────────────────────────────────────────────────────────
export function RoutingTopologyMap() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [healthInfo, setHealthInfo] = useState<HealthInfo | null>(null);
  const [healthLoaded, setHealthLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((info) => { if (!cancelled) { setHealthInfo(info); setHealthLoaded(true); } })
      .catch(() => { if (!cancelled) { setHealthLoaded(true); } });
    return () => { cancelled = true; };
  }, []);

  const aionMode = healthInfo?.aion_mode ?? "not_configured";
  // Once health is loaded, treat missing/empty active_modules as "all on" rather than "all off".
  const activeModules: Set<string> | null = healthLoaded
    ? new Set(healthInfo?.active_modules?.length ? healthInfo.active_modules : ["estixe", "nomos", "metis"])
    : null;

  const modeColor = MODE_COLORS[aionMode] ?? MODE_COLORS.not_configured;
  const modeLabel = MODE_LABELS[aionMode] ?? aionMode;
  const modeDescription = MODE_DESCRIPTIONS[aionMode] ?? MODE_DESCRIPTIONS.not_configured;

  const activeNode = NODES.find((n) => n.id === activeId) ?? null;

  const visibleEdges = EDGES.filter((e) => isEdgeForMode(e, aionMode));

  // Edges highlighted on node hover/select
  const highlightedEdgeIds = activeId
    ? new Set(visibleEdges.filter((e) => e.fromId === activeId || e.toId === activeId).map((e) => e.fromId + e.toId + (e.isResponse ? "_r" : "")))
    : null;

  const popupLeft = activeNode
    ? activeNode.cx + activeNode.w / 2 + 8 > W * 0.75
      ? activeNode.cx - activeNode.w / 2 - 220
      : activeNode.cx + activeNode.w / 2 + 8
    : 0;
  const popupTop = activeNode
    ? Math.max(4, Math.min(activeNode.cy - 60, H - 200))
    : 0;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
      {/* Header */}
      <div className="flex flex-col gap-2 border-b border-[var(--color-border)] px-6 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
            <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-primary)]" />
            Mapa de roteamento
          </h2>
          <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
            Clique em qualquer nó para ver as métricas. Linhas tracejadas = rotas de menor volume.
          </p>
        </div>

        {/* Mode badge */}
        <div className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 ring-1 ${modeColor.bg} ${modeColor.ring}`}>
          <span className={`relative flex h-2.5 w-2.5 shrink-0`}>
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${modeColor.dot}`} />
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${modeColor.dot}`} />
          </span>
          <div className="min-w-0">
            <div className={`text-[10px] font-bold uppercase tracking-widest ${modeColor.text}`}>
              Modo · {modeLabel}
            </div>
            <div className="mt-0.5 max-w-[280px] text-[11px] leading-snug text-[var(--color-text-muted)]">
              {modeDescription}
            </div>
          </div>
        </div>
      </div>

      {/* Canvas */}
      <div
        className="relative w-full"
        style={{ paddingTop: `${(H / W) * 100}%` }}
      >
        <div className="absolute inset-0">
          {/* ── SVG layer (lines + animation) ── */}
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="absolute inset-0 h-full w-full"
            style={{ pointerEvents: "none" }}
            preserveAspectRatio="xMidYMid meet"
          >
            <style>{`
              /* Decreasing dashoffset = dashes travel in the path's direction (x1→x2). */
              @keyframes aion-flow-fwd {
                from { stroke-dashoffset: 24; }
                to   { stroke-dashoffset: 0; }
              }
              .aion-flow {
                stroke-dasharray: 4 20;
                stroke-linecap: round;
                animation: aion-flow-fwd 1.6s linear infinite;
                pointer-events: none;
              }
              /* Response edges already point from model→gateway→client in the EDGES table,
                 so the same forward animation is the correct visual direction; we just slow
                 it down to differentiate "request" from "response" feel. */
              .aion-flow-rev {
                stroke-dasharray: 4 20;
                stroke-linecap: round;
                animation: aion-flow-fwd 2.4s linear infinite;
                pointer-events: none;
              }
            `}</style>

            <defs>
              {EDGES.map((e) => (
                <marker
                  key={`arrow-${e.fromId}-${e.toId}-${e.isResponse ? "r" : "f"}`}
                  id={`arrow-${e.fromId}-${e.toId}-${e.isResponse ? "r" : "f"}`}
                  markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"
                >
                  <path d="M0,0 L0,6 L6,3 z" fill={e.color} />
                </marker>
              ))}
            </defs>

            {visibleEdges.map((edge) => {
              const fromNode = NODES.find((n) => n.id === edge.fromId);
              const toNode = NODES.find((n) => n.id === edge.toId);
              const fromDisabled = fromNode ? isModuleDisabled(fromNode, activeModules) : false;
              const toDisabled = toNode ? isModuleDisabled(toNode, activeModules) : false;
              const edgeDisabled = fromDisabled || toDisabled;

              const edgeKey = edge.fromId + edge.toId + (edge.isResponse ? "_r" : "");
              const isHighlighted = highlightedEdgeIds
                ? highlightedEdgeIds.has(edgeKey)
                : false;

              const baseOpacity = edgeDisabled
                ? 0.1
                : highlightedEdgeIds
                  ? isHighlighted ? 1 : 0.18
                  : edge.isResponse ? 0.55 : 0.5;

              const midX = (edge.x1 + edge.x2) / 2;
              const midY = (edge.y1 + edge.y2) / 2;

              const pathD = bp(edge.x1, edge.y1, edge.x2, edge.y2);

              return (
                <g key={edgeKey} opacity={baseOpacity}>
                  {/* Static line */}
                  <path
                    d={pathD}
                    stroke={edge.color}
                    strokeWidth={isHighlighted ? 2 : 1.5}
                    fill="none"
                    strokeDasharray={edge.dashed ? "5 4" : undefined}
                    markerEnd={`url(#arrow-${edge.fromId}-${edge.toId}-${edge.isResponse ? "r" : "f"})`}
                    style={{ transition: "opacity 0.2s, stroke-width 0.2s" }}
                  />
                  {/* Animated overlay — flowing dots traveling along the path */}
                  {!edgeDisabled && (
                    <path
                      d={pathD}
                      stroke={edge.color}
                      strokeWidth={2.2}
                      fill="none"
                      className={edge.isResponse ? "aion-flow-rev" : "aion-flow"}
                      opacity={isHighlighted ? 0.95 : 0.7}
                    />
                  )}
                  {edge.label && (
                    <text
                      x={midX}
                      y={midY - 6}
                      textAnchor="middle"
                      fontSize="11"
                      fontWeight="600"
                      fill={edge.color}
                      style={{ fontFamily: "monospace" }}
                    >
                      {edge.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>

          {/* ── Node layer (HTML divs) ── */}
          {NODES.map((node) => {
            const disabled = isModuleDisabled(node, activeModules);
            const isActive = node.id === activeId;
            const isDimmed = activeId !== null && !isActive && !visibleEdges.some(
              (e) => (e.fromId === activeId && e.toId === node.id) ||
                     (e.toId === activeId && e.fromId === node.id)
            );

            const leftPct = ((node.cx - node.w / 2) / W) * 100;
            const topPct = ((node.cy - node.h / 2) / H) * 100;
            const widthPct = (node.w / W) * 100;

            // Dashed border when module is OFF
            const borderStyle = disabled ? { borderStyle: "dashed" as const } : undefined;

            return (
              <button
                key={node.id}
                onClick={() => setActiveId(isActive ? null : node.id)}
                className={`
                  absolute rounded-xl border px-2.5 py-1.5 text-left
                  transition-all duration-200 cursor-pointer
                  ${node.bg} ${node.accent}
                  ${isActive ? "ring-2 ring-offset-1 ring-offset-transparent scale-105 shadow-lg " + node.accent.replace("border-", "ring-") : "hover:scale-105 hover:brightness-125"}
                  ${disabled ? "opacity-40 grayscale" : isDimmed ? "opacity-25" : "opacity-100"}
                `}
                style={{
                  left: `${leftPct}%`,
                  top: `${topPct}%`,
                  width: `${widthPct}%`,
                  ...borderStyle,
                }}
              >
                <div className="flex items-start justify-between gap-1">
                  <div className="min-w-0">
                    <div className={`truncate text-xs font-semibold leading-tight ${node.textAccent}`}>
                      {node.label}
                    </div>
                    <div className="mt-0.5 truncate text-[10px] leading-tight text-[var(--color-text-muted)]">
                      {node.sublabel}
                    </div>
                  </div>
                  {disabled && (
                    <span className="shrink-0 rounded border border-red-500/40 bg-red-950/60 px-1 py-px text-[8px] font-bold uppercase tracking-wider text-red-300">
                      OFF
                    </span>
                  )}
                </div>
                {node.type === "module" && !disabled && (
                  <div className={`mt-1.5 h-0.5 w-full rounded-full opacity-40`}
                       style={{ background: node.textAccent.includes("teal") ? "#2dd4bf" : "#38bdf8" }}
                  />
                )}
                {node.type === "client" && !disabled && (
                  <div className="mt-1 h-0.5 w-full rounded-full bg-indigo-400/50" />
                )}
              </button>
            );
          })}

          {/* ── Detail popup ── */}
          {activeNode && (
            <div
              className="absolute z-10 w-52 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] p-3 shadow-2xl"
              style={{
                left: `${(popupLeft / W) * 100}%`,
                top: `${(popupTop / H) * 100}%`,
              }}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className={`truncate text-xs font-bold ${activeNode.textAccent}`}>
                  {activeNode.label}
                </span>
                {activeNode.moduleId && isModuleDisabled(activeNode, activeModules) && (
                  <span className="shrink-0 rounded border border-red-500/40 bg-red-950/60 px-1 py-px text-[9px] font-bold uppercase tracking-wider text-red-300">
                    desligado
                  </span>
                )}
                <button
                  onClick={() => setActiveId(null)}
                  className="cursor-pointer text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="space-y-1.5">
                {Object.entries(activeNode.stats).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-2">
                    <span className="text-[10px] text-[var(--color-text-muted)]">{k}</span>
                    <span className="font-mono text-[11px] font-semibold text-[var(--color-text)]">{v}</span>
                  </div>
                ))}
              </div>
              {activeNode.moduleId && (
                <p className="mt-2 border-t border-[var(--color-border)] pt-2 text-[9px] leading-snug text-[var(--color-text-muted)]/70">
                  Para ligar/desligar este módulo, vá em <span className="font-semibold text-[var(--color-text-muted)]">Operação → Módulos ativos</span>.
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Footer legend */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-[var(--color-border)] px-6 py-3">
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <span className="h-0.5 w-5 rounded-full bg-indigo-400/70" />
          Cliente
        </span>
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <span className="h-0.5 w-5 rounded-full bg-teal-400/60" />
          Proteção
        </span>
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <span className="h-0.5 w-5 rounded-full bg-sky-400/60" />
          Roteamento
        </span>
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <span className="h-0.5 w-5 rounded-full bg-emerald-400/60" />
          Resposta
        </span>
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <svg width="20" height="4" className="inline">
            <line x1="0" y1="2" x2="20" y2="2" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" />
          </svg>
          rota tracejada = baixo volume
        </span>
        <span className="ml-auto text-xs text-[var(--color-text-muted)]">
          Clique em um nó para inspecionar
        </span>
      </div>
    </div>
  );
}
