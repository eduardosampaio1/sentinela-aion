"use client";

import { type ReactNode } from "react";

type Variant = "default" | "success" | "warning" | "error" | "info" | "muted" | "solid-success";

const styles: Record<Variant, string> = {
  default: "bg-white/10 text-slate-300",
  success: "bg-green-900/30 text-green-400",
  warning: "bg-amber-900/30 text-amber-400",
  error: "bg-red-900/30 text-red-400",
  info: "bg-blue-900/30 text-blue-400",
  muted: "bg-white/5 text-slate-400",
  "solid-success": "bg-green-600 text-white",
};

export function Badge({
  variant = "default",
  children,
  dot,
  pulse,
}: {
  variant?: Variant;
  children: ReactNode;
  dot?: boolean;
  pulse?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[variant]}`}
    >
      {dot && (
        <span className="relative flex h-2 w-2">
          {pulse && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-40" />
          )}
          <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
        </span>
      )}
      {children}
    </span>
  );
}
