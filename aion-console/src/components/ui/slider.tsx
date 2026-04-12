"use client";

import { HelpCircle } from "lucide-react";
import { useState } from "react";

export function Slider({
  label,
  description,
  lowLabel,
  highLabel,
  tooltip,
  value,
  onChange,
  min = 0,
  max = 100,
  step = 10,
}: {
  label: string;
  description?: string;
  lowLabel: string;
  highLabel: string;
  tooltip?: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  const [showTooltip, setShowTooltip] = useState(false);
  const percent = ((value - min) / (max - min)) * 100;

  return (
    <div className="py-4">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-sm font-semibold text-[var(--color-text)]">{label}</span>
        <span className="font-[family-name:var(--font-mono)] text-xs font-medium text-[var(--color-primary)]">
          {value}
        </span>
        {tooltip && (
          <div className="relative">
            <button
              className="cursor-pointer text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)]"
              onMouseEnter={() => setShowTooltip(true)}
              onMouseLeave={() => setShowTooltip(false)}
              aria-label={tooltip}
            >
              <HelpCircle className="h-3.5 w-3.5" />
            </button>
            {showTooltip && (
              <div className="absolute bottom-full left-0 z-10 mb-2 w-64 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-text-muted)] shadow-lg">
                {tooltip}
              </div>
            )}
          </div>
        )}
      </div>
      {description && (
        <p className="mb-3 text-xs text-[var(--color-text-muted)]">{description}</p>
      )}
      <div className="flex items-center gap-3">
        <span className="w-24 text-right text-xs text-[var(--color-text-muted)]">{lowLabel}</span>
        <div className="relative flex-1">
          <div className="h-2 rounded-full bg-white/15">
            <div
              className="h-full rounded-full bg-[var(--color-primary)] transition-all duration-150"
              style={{ width: `${percent}%` }}
            />
          </div>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(e) => onChange(Number(e.target.value))}
            className="absolute inset-0 h-2 w-full cursor-pointer appearance-none bg-transparent [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-primary)] [&::-webkit-slider-thumb]:shadow-md"
            aria-label={label}
          />
        </div>
        <span className="w-24 text-xs text-[var(--color-text-muted)]">{highLabel}</span>
      </div>
    </div>
  );
}
