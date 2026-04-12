"use client";

import { User, ChevronDown } from "lucide-react";

export function Topbar({ collapsed }: { collapsed: boolean }) {
  return (
    <header
      className={`fixed top-0 z-10 flex h-14 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-surface)] px-6 transition-all duration-200 ${
        collapsed ? "left-16" : "left-60"
      } right-0`}
    >
      <div />

      <div className="flex items-center gap-4">
        {/* Tenant selector */}
        <button className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] transition-colors hover:border-[var(--color-primary)] hover:text-[var(--color-text)]">
          <span className="font-[family-name:var(--font-mono)]">default</span>
          <ChevronDown className="h-3 w-3" />
        </button>

        {/* User */}
        <button className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-[var(--color-text-muted)] transition-colors hover:bg-white/5 hover:text-[var(--color-text)]">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--color-primary)]/10 text-[var(--color-primary)]">
            <User className="h-4 w-4" />
          </div>
        </button>
      </div>
    </header>
  );
}
