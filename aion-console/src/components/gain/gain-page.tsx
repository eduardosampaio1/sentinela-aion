"use client";

import { useState } from "react";
import {
  Zap,
  Coins,
  Timer,
  Hash,
  AlertTriangle,
  Info,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  XCircle,
} from "lucide-react";
import { MetricCard } from "@/components/ui/metric-card";
import { DemoBanner } from "@/components/ui/demo-banner";
import { TimeRangeSelect } from "@/components/ui/time-range-select";
import type { TimeRange } from "@/components/ui/time-range-select";
import { Badge } from "@/components/ui/badge";
import { useApiData } from "@/lib/use-api-data";
import { getGainReport } from "@/lib/api/gains";
import { mockGainReport } from "@/lib/mock-data";
import { useT } from "@/lib/i18n";
import type { GainSavingDriver, GainIntentBreakdown, GainModelBreakdown, GainStrategyBreakdown } from "@/lib/types";

const TIME_RANGE_DAYS: Record<TimeRange, number> = {
  live: 1, "1h": 1, "4h": 1, "24h": 1, "2d": 2, "7d": 7, "14d": 14, "30d": 30,
};

function fmtUsd(v: number): string {
  return v < 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(2)}`;
}

function fmtLatency(ms: number): string {
  if (ms >= 3_600_000) return `${(ms / 3_600_000).toFixed(1)}h`;
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(0)}min`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(0)}s`;
  return `${ms}ms`;
}

function fmtNum(n: number): string {
  return n.toLocaleString();
}

function ConfidenceBadge({ level }: { level: "low" | "medium" | "high" }) {
  const t = useT();
  if (level === "high") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-green-800/40 bg-green-900/20 px-3 py-1 text-xs font-semibold text-green-400">
        <CheckCircle2 className="h-3.5 w-3.5" />
        {t("gain_report.confidence.label")}: {t("gain_report.confidence.high")}
      </span>
    );
  }
  if (level === "medium") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-800/40 bg-amber-900/20 px-3 py-1 text-xs font-semibold text-amber-400">
        <AlertCircle className="h-3.5 w-3.5" />
        {t("gain_report.confidence.label")}: {t("gain_report.confidence.medium")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-red-800/40 bg-red-900/20 px-3 py-1 text-xs font-semibold text-red-400">
      <XCircle className="h-3.5 w-3.5" />
      {t("gain_report.confidence.label")}: {t("gain_report.confidence.low")}
    </span>
  );
}

function EstimatedBadge() {
  const t = useT();
  return (
    <span className="ml-1 rounded bg-amber-900/30 px-1 py-0.5 text-[10px] font-semibold text-amber-400">
      {t("gain_report.tables.estimated_badge")}
    </span>
  );
}

function CumulativeBadge() {
  const t = useT();
  return (
    <span className="ml-1 rounded bg-sky-900/30 px-1 py-0.5 text-[10px] font-semibold text-sky-400">
      {t("gain_report.tables.cumulative_badge")}
    </span>
  );
}

function DriversTable({ rows }: { rows: GainSavingDriver[] }) {
  const t = useT();
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h3 className="mb-4 text-sm font-semibold text-[var(--color-text)]">
        {t("gain_report.tables.drivers_title")}
      </h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-[var(--color-text-muted)]">
            <th className="pb-2 font-medium">{t("gain_report.tables.driver_col")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.calls_avoided")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.cost_avoided")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.pct")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border)]">
          {rows.map((r) => (
            <tr key={r.name} className="py-1.5">
              <td className="py-2 font-mono text-[var(--color-text)]">
                {r.name}
                {r.is_estimated && <EstimatedBadge />}
              </td>
              <td className="py-2 text-right text-[var(--color-text-muted)]">{fmtNum(r.calls_avoided)}</td>
              <td className="py-2 text-right font-mono text-green-400">{fmtUsd(r.cost_avoided_usd)}</td>
              <td className="py-2 text-right text-[var(--color-text-muted)]">{r.pct_of_total_savings.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IntentsTable({ rows }: { rows: GainIntentBreakdown[] }) {
  const t = useT();
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h3 className="mb-4 text-sm font-semibold text-[var(--color-text)]">
        {t("gain_report.tables.intents_title")}
      </h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-[var(--color-text-muted)]">
            <th className="pb-2 font-medium">{t("gain_report.tables.intent_col")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.calls_avoided")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.cost_avoided")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.precision")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border)]">
          {rows.map((r) => (
            <tr key={r.intent}>
              <td className="py-2 font-mono text-[var(--color-text)]">
                {r.intent}
                {r.source === "intent_memory_cumulative" && <CumulativeBadge />}
              </td>
              <td className="py-2 text-right text-[var(--color-text-muted)]">{fmtNum(r.calls_avoided)}</td>
              <td className="py-2 text-right font-mono text-green-400">{fmtUsd(r.cost_avoided_usd)}</td>
              <td className="py-2 text-right text-[var(--color-text-muted)]">{(r.bypass_accuracy * 100).toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModelsTable({ rows }: { rows: GainModelBreakdown[] }) {
  const t = useT();
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h3 className="mb-4 text-sm font-semibold text-[var(--color-text)]">
        {t("gain_report.tables.models_title")}
      </h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-[var(--color-text-muted)]">
            <th className="pb-2 font-medium">{t("gain_report.tables.model_col")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.calls_routed")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.cost_avoided")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border)]">
          {rows.map((r) => (
            <tr key={r.model_used}>
              <td className="py-2 font-mono text-[var(--color-text)]">{r.model_used}</td>
              <td className="py-2 text-right text-[var(--color-text-muted)]">{fmtNum(r.calls_routed)}</td>
              <td className="py-2 text-right font-mono text-green-400">{fmtUsd(r.cost_avoided_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StrategiesTable({ rows }: { rows: GainStrategyBreakdown[] }) {
  const t = useT();
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h3 className="mb-4 text-sm font-semibold text-[var(--color-text)]">
        {t("gain_report.tables.strategies_title")}
      </h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-[var(--color-text-muted)]">
            <th className="pb-2 font-medium">{t("gain_report.tables.strategy_col")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.occurrences")}</th>
            <th className="pb-2 text-right font-medium">{t("gain_report.tables.cost_avoided")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border)]">
          {rows.map((r) => (
            <tr key={r.strategy}>
              <td className="py-2 text-[var(--color-text)]">{r.label}</td>
              <td className="py-2 text-right text-[var(--color-text-muted)]">{fmtNum(r.count)}</td>
              <td className="py-2 text-right font-mono text-green-400">
                {r.cost_avoided_usd > 0 ? fmtUsd(r.cost_avoided_usd) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function GainPage() {
  const t = useT();
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");

  const days = TIME_RANGE_DAYS[timeRange];
  const fromDate = new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
  const toDate = new Date().toISOString().slice(0, 10);

  const { data, isDemo, loading, refetch } = useApiData(
    () => getGainReport({ from: fromDate, to: toDate }),
    mockGainReport,
    { treatEmptyAsDemo: (d) => d.summary.total_requests === 0 },
  );

  const s = data.summary;
  const b = data.breakdowns;
  const isEmpty = s.total_requests === 0;

  return (
    <div className="space-y-6">
      {isDemo && <DemoBanner />}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-[var(--color-text)]">
            {t("gain_report.title")}
          </h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            {t("gain_report.subtitle").replace("{n}", String(days))}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ConfidenceBadge level={data.confidence} />
          <TimeRangeSelect value={timeRange} onChange={setTimeRange} />
          <button
            onClick={refetch}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)] disabled:opacity-40"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Limitations banner */}
      {data.limitations.length > 0 && (
        <div className="rounded-xl border border-amber-800/30 bg-amber-900/10 p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-amber-400">
            <AlertTriangle className="h-4 w-4" />
            {t("gain_report.limitations.title")}
          </div>
          <ul className="space-y-1">
            {data.limitations.map((lim, i) => (
              <li key={i} className="text-xs text-amber-300/80">• {lim}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Empty state */}
      {isEmpty ? (
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-8 py-16 text-center">
          <p className="text-sm text-[var(--color-text-muted)]">{t("gain_report.empty")}</p>
        </div>
      ) : (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <MetricCard
              label={t("gain_report.kpi.calls_avoided")}
              value={fmtNum(s.llm_calls_avoided)}
              icon={<Zap />}
              trend={{ value: Math.round(s.llm_calls_avoided_pct * 100), positive: true }}
            />
            <MetricCard
              label={t("gain_report.kpi.tokens_saved")}
              value={fmtNum(s.tokens_saved)}
              icon={<Hash />}
            />
            <MetricCard
              label={t("gain_report.kpi.cost_avoided")}
              value={fmtUsd(s.estimated_cost_avoided_usd)}
              icon={<Coins />}
              tooltip={t("gain_report.tables.estimated_badge")}
            />
            <MetricCard
              label={t("gain_report.kpi.latency_avoided")}
              value={fmtLatency(s.estimated_latency_avoided_ms)}
              icon={<Timer />}
              tooltip={t("gain_report.tables.estimated_badge")}
            />
          </div>

          {/* LLM call bypass progress bar */}
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-4">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="text-[var(--color-text-muted)]">{t("gain_report.kpi.calls_avoided")}</span>
              <span className="font-mono font-semibold text-[var(--color-primary)]">
                {(s.llm_calls_avoided_pct * 100).toFixed(1)}% {t("gain_report.kpi.of_total")}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-[var(--color-primary)]"
                style={{ width: `${(s.llm_calls_avoided_pct * 100).toFixed(1)}%` }}
              />
            </div>
            <div className="mt-1.5 flex justify-between text-[10px] text-[var(--color-text-muted)]">
              <span>{fmtNum(s.llm_calls_avoided)} avoided</span>
              <span>{fmtNum(s.total_requests)} total</span>
            </div>
          </div>

          {/* Breakdowns grid */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <DriversTable rows={b.top_saving_drivers} />
            <IntentsTable rows={b.top_intents} />
            <ModelsTable rows={b.top_models} />
            <StrategiesTable rows={b.top_strategies} />
          </div>

          {/* Calculation notes */}
          {data.calculation_notes.length > 0 && (
            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                <Info className="h-3.5 w-3.5" />
                {t("gain_report.calc_notes.title")}
              </div>
              <ul className="space-y-1">
                {data.calculation_notes.map((note, i) => (
                  <li key={i} className="text-xs text-[var(--color-text-muted)]">• {note}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
