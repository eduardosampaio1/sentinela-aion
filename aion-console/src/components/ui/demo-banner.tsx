"use client";

import { useState } from "react";
import { AlertTriangle, RefreshCw, X } from "lucide-react";

interface DemoBannerProps {
  /** Called when the user clicks "Tentar reconectar". */
  onRetry?: () => void;
}

/**
 * Displays a subtle amber banner when the frontend is using fallback mock data
 * because the backend is unavailable.
 *
 * @example
 *   const { isDemo, refetch } = useApiData(getStats, mockStats);
 *   {isDemo && <DemoBanner onRetry={refetch} />}
 */
export function DemoBanner({ onRetry }: DemoBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  return (
    <div className="mb-5 flex items-center gap-3 rounded-lg border border-amber-800/40 bg-amber-950/30 px-4 py-2.5 text-sm text-amber-400">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className="flex-1 text-xs">
        Backend indisponível — exibindo dados de demonstração
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 rounded border border-amber-800/40 px-2 py-1 text-[10px] font-medium hover:bg-amber-900/30 transition-colors cursor-pointer"
        >
          <RefreshCw className="h-3 w-3" />
          Reconectar
        </button>
      )}
      <button
        onClick={() => setDismissed(true)}
        className="rounded p-0.5 hover:bg-amber-900/30 transition-colors cursor-pointer"
        aria-label="Dispensar aviso"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
