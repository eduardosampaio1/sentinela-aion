"use client";

import { useState, useRef, useEffect } from "react";
import { Clock, ChevronDown, Zap, Check } from "lucide-react";

export type TimeRange = "live" | "1h" | "4h" | "24h" | "2d" | "7d" | "14d" | "30d";

interface RangeOption {
  id: TimeRange;
  label: string;
  disabled?: boolean;
}

const ranges: RangeOption[] = [
  { id: "live", label: "Live tail" },
  { id: "1h", label: "Last hour" },
  { id: "4h", label: "Last 4 hours" },
  { id: "24h", label: "Last 24 hours" },
  { id: "2d", label: "Last 2 days" },
  { id: "7d", label: "Last 7 days" },
  { id: "14d", label: "Last 14 days", disabled: true },
  { id: "30d", label: "Last 30 days", disabled: true },
];

export function timeRangeMs(range: TimeRange): number {
  const map: Record<TimeRange, number> = {
    live: 5 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "2d": 2 * 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "14d": 14 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
  };
  return map[range];
}

export function TimeRangeSelect({
  value,
  onChange,
}: {
  value: TimeRange;
  onChange: (v: TimeRange) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const current = ranges.find((r) => r.id === value);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-medium text-[var(--color-text)] hover:bg-white/5 transition-colors"
      >
        <Clock className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
        {current?.label}
        <ChevronDown
          className={`h-3.5 w-3.5 text-[var(--color-text-muted)] transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-20 w-44 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-xl overflow-hidden py-1">
          {ranges.map((r) => (
            <button
              key={r.id}
              disabled={r.disabled}
              onClick={() => {
                onChange(r.id);
                setOpen(false);
              }}
              className={`flex w-full items-center gap-2 px-4 py-2 text-sm transition-colors ${
                r.disabled
                  ? "cursor-not-allowed text-[var(--color-text-muted)]/40"
                  : r.id === value
                  ? "bg-violet-600/20 text-[var(--color-text)]"
                  : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)]"
              }`}
            >
              {r.id === "live" ? (
                <Zap className="h-3.5 w-3.5 shrink-0 text-amber-400" />
              ) : (
                <Clock className="h-3.5 w-3.5 shrink-0 opacity-0" />
              )}
              {r.label}
              {r.id === value && !r.disabled && (
                <Check className="ml-auto h-3.5 w-3.5 text-violet-400" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
