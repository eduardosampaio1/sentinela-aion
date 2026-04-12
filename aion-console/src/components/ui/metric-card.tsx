"use client";

import { HelpCircle } from "lucide-react";
import { type ReactNode, useState } from "react";

export function MetricCard({
  label,
  value,
  unit,
  prefix,
  tooltip,
  icon,
  trend,
}: {
  label: string;
  value: string | number;
  unit?: string;
  prefix?: string;
  tooltip?: string;
  icon?: ReactNode;
  trend?: { value: number; positive: boolean };
}) {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div className="relative rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 transition-shadow duration-200 hover:shadow-md">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2 text-[var(--color-text-muted)]">
          {icon && <span className="h-4 w-4">{icon}</span>}
          <span className="text-xs font-medium uppercase tracking-wider">{label}</span>
        </div>
        {tooltip && (
          <button
            className="cursor-pointer text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)]"
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
            aria-label={tooltip}
          >
            <HelpCircle className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="mt-3 flex items-baseline gap-1">
        {prefix && (
          <span className="font-[family-name:var(--font-mono)] text-lg font-medium text-[var(--color-text-muted)]">
            {prefix}
          </span>
        )}
        <span className="font-[family-name:var(--font-mono)] text-3xl font-bold text-[var(--color-primary)]">
          {value}
        </span>
        {unit && (
          <span className="font-[family-name:var(--font-mono)] text-sm font-medium text-[var(--color-text-muted)]">
            {unit}
          </span>
        )}
      </div>

      {trend && (
        <div className={`mt-2 text-xs font-medium ${trend.positive ? "text-green-600" : "text-red-600"}`}>
          {trend.positive ? "+" : ""}{trend.value}%
        </div>
      )}

      {showTooltip && tooltip && (
        <div className="absolute right-0 top-full z-10 mt-1 max-w-xs rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-text-muted)] shadow-lg">
          {tooltip}
        </div>
      )}
    </div>
  );
}
