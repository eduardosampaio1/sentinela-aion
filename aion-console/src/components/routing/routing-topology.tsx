"use client";

import { useState } from "react";
import { X } from "lucide-react";

// ─── Canvas dimensions (SVG viewBox) ──────────────────────────────────────────
const W = 900;
const H = 430;

// ─── Bezier path helper ────────────────────────────────────────────────────────
function bp(x1: number, y1: number, x2: number, y2: number) {
  const mx = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
}

// ─── Types ─────────────────────────────────────────────────────────────────────
type NodeDef = {
  id: string;
  cx: number;
  cy: number;
  w: number;
  h: number;
  label: string;
  sublabel: string;
  accent: string;           // Tailwind border/ring color class
  bg: string;               // Tailwind bg class
  textAccent: string;       // Tailwind text color
  type: "entry" | "module" | "output" | "model";
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
};

// ─── Node definitions ─────────────────────────────────────────────────────────
const NODES: NodeDef[] = [
  {
    id: "entry",
    cx: 58, cy: 215,
    w: 84, h: 44,
    label: "Request",
    sublabel: "100% das mensagens",
    accent: "border-slate-600",
    bg: "bg-slate-800/60",
    textAccent: "text-slate-300",
    type: "entry",
    stats: {
      "Volume / dia": "22.840",
      "Pico": "1.200 req/h",
      "Latência entrada": "< 1ms",
    },
  },
  {
    id: "estixe",
    cx: 235, cy: 215,
    w: 136, h: 84,
    label: "ESTIXE",
    sublabel: "proteção & bypass",
    accent: "border-teal-600/70",
    bg: "bg-teal-950/50",
    textAccent: "text-teal-400",
    type: "module",
    stats: {
      "Decisões / dia": "22.840",
      "Bypass": "40%",
      "Bloqueios": "15%",
      "Para NOMOS": "45%",
      "Latência": "8ms",
    },
  },
  {
    id: "bypass",
    cx: 490, cy: 80,
    w: 136, h: 52,
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
    cx: 490, cy: 180,
    w: 136, h: 52,
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
    cx: 490, cy: 322,
    w: 136, h: 84,
    label: "NOMOS",
    sublabel: "roteamento IA",
    accent: "border-sky-600/70",
    bg: "bg-sky-950/50",
    textAccent: "text-sky-400",
    type: "module",
    stats: {
      "Rotas / dia": "10.278",
      "Acurácia": "94%",
      "Latência": "18ms",
      "Economia / dia": "US$ 16",
    },
  },
  {
    id: "gpt4o",
    cx: 740, cy: 207,
    w: 136, h: 50,
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
    cx: 740, cy: 275,
    w: 136, h: 50,
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
    cx: 740, cy: 343,
    w: 136, h: 50,
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
    cx: 740, cy: 411,
    w: 136, h: 50,
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
// x/y are the exact SVG start/end points of each line
const EDGES: EdgeDef[] = [
  // Entry → ESTIXE
  { fromId: "entry", toId: "estixe",   x1: 100, y1: 215, x2: 167, y2: 215, color: "#475569" },
  // ESTIXE → Bypass
  { fromId: "estixe", toId: "bypass",  x1: 303, y1: 198, x2: 422, y2: 80,  color: "#2dd4bf", label: "40%" },
  // ESTIXE → Block
  { fromId: "estixe", toId: "block",   x1: 303, y1: 215, x2: 422, y2: 180, color: "#f87171", label: "15%", dashed: true },
  // ESTIXE → NOMOS
  { fromId: "estixe", toId: "nomos",   x1: 303, y1: 232, x2: 422, y2: 322, color: "#38bdf8", label: "45%" },
  // NOMOS → models
  { fromId: "nomos", toId: "gpt4o",    x1: 558, y1: 308, x2: 672, y2: 207, color: "#a78bfa", label: "14%" },
  { fromId: "nomos", toId: "gpt4mini", x1: 558, y1: 318, x2: 672, y2: 275, color: "#38bdf8", label: "25%" },
  { fromId: "nomos", toId: "claude",   x1: 558, y1: 330, x2: 672, y2: 343, color: "#fbbf24", label: "4%",  dashed: true },
  { fromId: "nomos", toId: "gemini",   x1: 558, y1: 338, x2: 672, y2: 411, color: "#4ade80", label: "2%",  dashed: true },
];

// ─── Component ────────────────────────────────────────────────────────────────
export function RoutingTopologyMap() {
  const [activeId, setActiveId] = useState<string | null>(null);

  const activeNode = NODES.find((n) => n.id === activeId) ?? null;

  // Which edges are highlighted when a node is active
  const highlightedEdgeIds = activeId
    ? new Set(EDGES.filter((e) => e.fromId === activeId || e.toId === activeId).map((e) => e.fromId + e.toId))
    : null;

  // Popup position: to the right of the node if it fits, otherwise to the left
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
      <div className="border-b border-[var(--color-border)] px-6 py-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text)]">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--color-primary)]" />
          Mapa de roteamento
        </h2>
        <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
          Clique em qualquer nó para ver as métricas detalhadas. Linhas tracejadas = rotas de menor volume.
        </p>
      </div>

      {/* Canvas */}
      <div
        className="relative w-full"
        style={{ paddingTop: `${(H / W) * 100}%` }}
      >
        <div className="absolute inset-0">
          {/* ── SVG layer (lines only) ── */}
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="absolute inset-0 h-full w-full"
            style={{ pointerEvents: "none" }}
            preserveAspectRatio="xMidYMid meet"
          >
            <defs>
              <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L0,6 L6,3 z" fill="#475569" />
              </marker>
              {EDGES.map((e) => (
                <marker
                  key={`arrow-${e.fromId}-${e.toId}`}
                  id={`arrow-${e.fromId}-${e.toId}`}
                  markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"
                >
                  <path d="M0,0 L0,6 L6,3 z" fill={e.color} />
                </marker>
              ))}
            </defs>

            {EDGES.map((edge) => {
              const edgeKey = edge.fromId + edge.toId;
              const isHighlighted = highlightedEdgeIds
                ? highlightedEdgeIds.has(edgeKey)
                : false;
              const opacity = highlightedEdgeIds
                ? isHighlighted ? 1 : 0.15
                : 0.45;

              const midX = (edge.x1 + edge.x2) / 2;
              const midY = (edge.y1 + edge.y2) / 2;

              return (
                <g key={edgeKey} opacity={opacity}>
                  <path
                    d={bp(edge.x1, edge.y1, edge.x2, edge.y2)}
                    stroke={edge.color}
                    strokeWidth={isHighlighted ? 2 : 1.5}
                    fill="none"
                    strokeDasharray={edge.dashed ? "5 4" : undefined}
                    markerEnd={`url(#arrow-${edge.fromId}-${edge.toId})`}
                    style={{ transition: "opacity 0.2s, stroke-width 0.2s" }}
                  />
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
            const isActive = node.id === activeId;
            const isDimmed = activeId !== null && !isActive && !EDGES.some(
              (e) => (e.fromId === activeId && e.toId === node.id) ||
                      (e.toId === activeId && e.fromId === node.id)
            );

            const leftPct = ((node.cx - node.w / 2) / W) * 100;
            const topPct = ((node.cy - node.h / 2) / H) * 100;
            const widthPct = (node.w / W) * 100;

            return (
              <button
                key={node.id}
                onClick={() => setActiveId(isActive ? null : node.id)}
                className={`
                  absolute rounded-xl border px-2.5 py-1.5 text-left
                  transition-all duration-200 cursor-pointer
                  ${node.bg} ${node.accent}
                  ${isActive ? "ring-2 ring-offset-1 ring-offset-transparent scale-105 shadow-lg " + node.accent.replace("border-", "ring-") : "hover:scale-102 hover:brightness-125"}
                  ${isDimmed ? "opacity-25" : "opacity-100"}
                `}
                style={{
                  left: `${leftPct}%`,
                  top: `${topPct}%`,
                  width: `${widthPct}%`,
                }}
              >
                <div className={`text-xs font-semibold leading-tight ${node.textAccent}`}>
                  {node.label}
                </div>
                <div className="mt-0.5 text-[10px] leading-tight text-[var(--color-text-muted)]">
                  {node.sublabel}
                </div>
                {node.type === "module" && (
                  <div className={`mt-1.5 h-0.5 w-full rounded-full opacity-40 ${node.bg.replace("bg-", "bg-").replace("/50", "").replace("/40", "")}`}
                       style={{ background: node.textAccent.includes("teal") ? "#2dd4bf" : "#38bdf8" }}
                  />
                )}
              </button>
            );
          })}

          {/* ── Detail popup ── */}
          {activeNode && (
            <div
              className="absolute z-10 w-48 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] p-3 shadow-2xl"
              style={{
                left: `${(popupLeft / W) * 100}%`,
                top: `${(popupTop / H) * 100}%`,
              }}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className={`text-xs font-bold ${activeNode.textAccent}`}>
                  {activeNode.label}
                </span>
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
            </div>
          )}
        </div>
      </div>

      {/* Footer legend */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-[var(--color-border)] px-6 py-3">
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <span className="h-0.5 w-5 rounded-full bg-teal-400/60" />
          ESTIXE
        </span>
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <span className="h-0.5 w-5 rounded-full bg-sky-400/60" />
          NOMOS
        </span>
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          <svg width="20" height="4" className="inline"><line x1="0" y1="2" x2="20" y2="2" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" /></svg>
          rota de baixo volume
        </span>
        <span className="ml-auto text-xs text-[var(--color-text-muted)]">
          Clique em um nó para inspecionar
        </span>
      </div>
    </div>
  );
}
