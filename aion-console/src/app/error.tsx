"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[AION Console] Unhandled error:", error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)]">
      <div className="max-w-md rounded-2xl border border-red-800/40 bg-[var(--color-surface)] p-8 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-red-900/30">
          <svg className="h-6 w-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
        </div>
        <h2 className="text-lg font-bold text-[var(--color-text)]">
          Algo deu errado
        </h2>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          Ocorreu um erro inesperado no console. A equipe foi notificada.
        </p>
        {error.digest && (
          <p className="mt-2 font-mono text-xs text-[var(--color-text-muted)]/50">
            Ref: {error.digest}
          </p>
        )}
        <button
          onClick={reset}
          className="mt-6 rounded-lg bg-[var(--color-cta)] px-5 py-2 text-sm font-semibold text-white hover:opacity-90 transition-opacity cursor-pointer"
        >
          Tentar novamente
        </button>
      </div>
    </div>
  );
}
