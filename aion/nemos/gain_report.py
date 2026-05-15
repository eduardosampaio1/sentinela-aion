"""AION Gain Report — consolidated economy view for a tenant over a time window.

Answers: "Quanto o AION economizou?"

Data source precedence (no double-counting):
  1. Economics buckets (canonical for cost avoided and LLM calls avoided)
  2. Per-request telemetry events (preferred for windowed intent/strategy breakdowns)
  3. Telemetry counters (fallback only, cumulative — not time-windowed)
  4. METIS optimization memory (sole source for tokens_saved — never summed with telemetry)
"""

from __future__ import annotations

import calendar
import datetime
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aion.nemos.gain_report")

_SCHEMA_VERSION = "1.0"
_DEFAULT_LLM_LATENCY_MS = 800   # heuristic if no model perf data in Redis
_BYPASS_OVERHEAD_MS = 20        # approximate bypass execution latency
_MAX_SCAN_ITERATIONS = 200      # cap Redis SCAN loops to avoid O(N) latency spikes


# ═══════════════════════════════════════════
# DTOs
# ═══════════════════════════════════════════


@dataclass
class GainSavingDriver:
    name: str
    calls_avoided: int
    cost_avoided_usd: float
    pct_of_total_savings: float
    source: str          # "intent_bypass_proxy" | future: "policy_stats"
    is_estimated: bool   # always True in v0 — PolicyStats not yet persisted


@dataclass
class GainIntentBreakdown:
    intent: str
    calls_avoided: int
    cost_avoided_usd: float
    bypass_accuracy: float   # 0–1, bypass_success_rate EMA or ratio
    source: str              # "events" | "intent_memory_cumulative"


@dataclass
class GainModelBreakdown:
    model_used: str
    calls_routed: int
    cost_avoided_usd: float  # savings_vs_default from economics bucket


@dataclass
class GainStrategyBreakdown:
    strategy: str    # "cache_hit" | "policy_bypass" | "compression" | "model_downgrade"
    label: str       # Portuguese human-readable
    count: int
    cost_avoided_usd: float


@dataclass
class AionGainReport:
    schema_version: str
    window_start: str           # ISO 8601
    window_end: str
    total_requests: int
    llm_calls_avoided: int
    llm_calls_avoided_pct: float
    tokens_saved: int
    estimated_cost_avoided_usd: float
    estimated_latency_avoided_ms: int   # always estimated; see calculation_notes
    top_saving_drivers: list[GainSavingDriver] = field(default_factory=list)
    top_intents: list[GainIntentBreakdown] = field(default_factory=list)
    top_models: list[GainModelBreakdown] = field(default_factory=list)
    top_strategies: list[GainStrategyBreakdown] = field(default_factory=list)
    confidence: str = "low"             # "low" | "medium" | "high"
    limitations: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    calculation_notes: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "summary": {
                "window_start": self.window_start,
                "window_end": self.window_end,
                "total_requests": self.total_requests,
                "llm_calls_avoided": self.llm_calls_avoided,
                "llm_calls_avoided_pct": round(self.llm_calls_avoided_pct, 4),
                "tokens_saved": self.tokens_saved,
                "estimated_cost_avoided_usd": round(self.estimated_cost_avoided_usd, 6),
                "estimated_latency_avoided_ms": self.estimated_latency_avoided_ms,
            },
            "breakdowns": {
                "top_saving_drivers": [
                    {
                        "name": d.name,
                        "calls_avoided": d.calls_avoided,
                        "cost_avoided_usd": round(d.cost_avoided_usd, 6),
                        "pct_of_total_savings": round(d.pct_of_total_savings, 3),
                        "source": d.source,
                        "is_estimated": d.is_estimated,
                    }
                    for d in self.top_saving_drivers
                ],
                "top_intents": [
                    {
                        "intent": i.intent,
                        "calls_avoided": i.calls_avoided,
                        "cost_avoided_usd": round(i.cost_avoided_usd, 6),
                        "bypass_accuracy": round(i.bypass_accuracy, 4),
                        "source": i.source,
                    }
                    for i in self.top_intents
                ],
                "top_models": [
                    {
                        "model_used": m.model_used,
                        "calls_routed": m.calls_routed,
                        "cost_avoided_usd": round(m.cost_avoided_usd, 6),
                    }
                    for m in self.top_models
                ],
                "top_strategies": [
                    {
                        "strategy": s.strategy,
                        "label": s.label,
                        "count": s.count,
                        "cost_avoided_usd": round(s.cost_avoided_usd, 6),
                    }
                    for s in self.top_strategies
                ],
            },
            "confidence": self.confidence,
            "limitations": self.limitations,
            "data_sources": self.data_sources,
            "calculation_notes": self.calculation_notes,
            "generated_at": self.generated_at,
        }


# ═══════════════════════════════════════════
# Builder
# ═══════════════════════════════════════════


async def _redis():
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            url, decode_responses=True,
            socket_timeout=1.0, socket_connect_timeout=1.0,
        )
        await r.ping()
        return r
    except Exception:
        return None


class GainReportBuilder:
    """Async builder — call `build(tenant, from_dt, to_dt)` to get AionGainReport."""

    async def build(
        self,
        tenant: str,
        from_dt: datetime.datetime,
        to_dt: datetime.datetime,
    ) -> AionGainReport:
        r = await _redis()
        limitations: list[str] = []
        data_sources: list[str] = []
        calculation_notes: list[str] = []
        generated_at = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # ── 1. Economics buckets (canonical for cost + LLM calls avoided) ─────
        total_requests = 0
        llm_calls_avoided = 0
        estimated_cost_avoided = 0.0
        economics_days = 0
        models_agg: dict[str, dict[str, Any]] = {}   # model → {calls_routed, cost_avoided_usd}

        cur = from_dt.date()
        end = to_dt.date()
        while cur <= end:
            date_str = cur.isoformat()
            if r:
                try:
                    raw = await r.get(f"aion:econ:{tenant}:daily:{date_str}")
                    if raw:
                        bucket = json.loads(raw)
                        summary = bucket.get("summary", {})
                        total_requests += summary.get("total_requests", 0)
                        estimated_cost_avoided += summary.get("total_savings", 0.0)
                        by_decision = bucket.get("by_decision", {})
                        llm_calls_avoided += by_decision.get("bypass", 0)
                        economics_days += 1
                        for model, mdata in bucket.get("by_model", {}).items():
                            if model not in models_agg:
                                models_agg[model] = {"calls_routed": 0, "cost_avoided_usd": 0.0}
                            models_agg[model]["calls_routed"] += mdata.get("requests", 0)
                            models_agg[model]["cost_avoided_usd"] += mdata.get("savings_vs_default", 0.0)
                except Exception:
                    logger.debug("gain_report: econ bucket read error %s", date_str, exc_info=True)
            cur += datetime.timedelta(days=1)

        if economics_days > 0:
            data_sources.append("economics_bucket")
            calculation_notes.append(
                f"estimated_cost_avoided from economics_bucket ({economics_days} days with data)"
            )
        else:
            # Fallback: cumulative counters (not time-windowed)
            try:
                from aion.shared.telemetry import get_counters
                counters = get_counters()
                llm_calls_avoided = counters.get("bypass_total", 0)
                estimated_cost_avoided = float(counters.get("cost_saved_total", 0.0))
                total_requests = counters.get("requests_total", 0)
                data_sources.append("telemetry_counters_cumulative")
                limitations.append(
                    "Economics bucket vazio — custo evitado usa contadores de telemetria "
                    "cumulativos (não filtrados pela janela de tempo selecionada)."
                )
                calculation_notes.append(
                    "estimated_cost_avoided from telemetry counters (cumulative, not windowed)"
                )
            except Exception:
                limitations.append("Nenhuma fonte de custo disponível — retornando zeros.")

        calculation_notes.append(
            "estimated_latency_avoided is estimated: "
            f"llm_calls_avoided × (avg_llm_latency_ms − {_BYPASS_OVERHEAD_MS}ms)"
        )

        # ── 2. Tokens saved (METIS only — never summed with telemetry counter) ─
        tokens_saved = 0
        metis_total = 0
        if r:
            try:
                raw = await r.get(f"aion:metis:{tenant}:optimization")
                if raw:
                    opt = json.loads(raw)
                    tokens_saved = int(opt.get("tokens_saved", 0))
                    metis_total = int(opt.get("total", 0))
                    data_sources.append("metis_optimization")
                    calculation_notes.append("tokens_saved sourced from METIS optimization only")
            except Exception:
                pass

        if tokens_saved == 0 and "metis_optimization" not in data_sources:
            try:
                from aion.shared.telemetry import get_counters
                counters = get_counters()
                tokens_saved = counters.get("tokens_saved_total", 0)
                if tokens_saved > 0:
                    if "telemetry_counters_cumulative" not in data_sources:
                        data_sources.append("telemetry_counters_cumulative")
                    calculation_notes.append(
                        "tokens_saved sourced from telemetry counter (cumulative fallback — METIS unavailable)"
                    )
                    limitations.append(
                        "METIS optimization memory indisponível — tokens_saved pode subestimar "
                        "economia de compressão de prompt."
                    )
            except Exception:
                pass

        # ── 3. Estimated latency avoided ──────────────────────────────────────
        avg_llm_latency_ms = float(_DEFAULT_LLM_LATENCY_MS)
        if r:
            try:
                latency_samples: list[float] = []
                cursor = 0
                for _ in range(_MAX_SCAN_ITERATIONS):
                    cursor, keys = await r.scan(cursor, match=f"aion:memory:{tenant}:*", count=50)
                    for key in keys:
                        raw = await r.get(key)
                        if raw:
                            mperf = json.loads(raw)
                            avg = float(mperf.get("avg_latency_ms", 0.0))
                            if avg > 0:
                                latency_samples.append(avg)
                    if cursor == 0:
                        break
                if latency_samples:
                    avg_llm_latency_ms = sum(latency_samples) / len(latency_samples)
                    if "model_performance" not in data_sources:
                        data_sources.append("model_performance")
            except Exception:
                pass

        estimated_latency_ms = int(
            llm_calls_avoided * max(0.0, avg_llm_latency_ms - _BYPASS_OVERHEAD_MS)
        )

        # ── 4. Fetch events once (shared for intents + strategies) ────────────
        # calendar.timegm always interprets timetuple as UTC — avoids naive-datetime
        # local-timezone ambiguity that datetime.timestamp() has on non-UTC servers.
        windowed_events: list[dict[str, Any]] = []
        if r:
            try:
                from aion.shared.telemetry import get_recent_events_redis
                from_ts = float(calendar.timegm(from_dt.timetuple()))
                to_ts = float(calendar.timegm(to_dt.timetuple()))
                all_events = await get_recent_events_redis(limit=2000, tenant=tenant)
                windowed_events = [
                    e for e in all_events
                    if from_ts <= float(e.get("timestamp", 0)) <= to_ts
                ]
                if windowed_events and "telemetry_events" not in data_sources:
                    data_sources.append("telemetry_events")
            except Exception:
                logger.debug("gain_report: events fetch failed", exc_info=True)

        # ── 5. Top intents (windowed events preferred, intent memory fallback) ─
        top_intents: list[GainIntentBreakdown] = []

        if windowed_events:
            intent_map: dict[str, dict[str, Any]] = {}
            for e in windowed_events:
                intent = (e.get("metadata") or {}).get("detected_intent", "")
                if not intent:
                    continue
                if intent not in intent_map:
                    intent_map[intent] = {
                        "calls_avoided": 0, "cost_avoided": 0.0,
                        "bypass_count": 0, "total_count": 0,
                    }
                intent_map[intent]["total_count"] += 1
                if e.get("decision") == "bypass":
                    intent_map[intent]["calls_avoided"] += 1
                    intent_map[intent]["cost_avoided"] += float(e.get("cost_saved", 0.0))
                    intent_map[intent]["bypass_count"] += 1

            for intent, agg in sorted(
                intent_map.items(), key=lambda x: x[1]["cost_avoided"], reverse=True
            )[:10]:
                total_c = agg["total_count"]
                top_intents.append(GainIntentBreakdown(
                    intent=intent,
                    calls_avoided=agg["calls_avoided"],
                    cost_avoided_usd=agg["cost_avoided"],
                    bypass_accuracy=agg["bypass_count"] / total_c if total_c > 0 else 0.0,
                    source="events",
                ))

        if not top_intents and r:
            # Fallback: cumulative intent memory
            try:
                cursor = 0
                intent_entries: list[dict[str, Any]] = []
                for _ in range(_MAX_SCAN_ITERATIONS):
                    cursor, keys = await r.scan(
                        cursor, match=f"aion:estixe:{tenant}:intent:*", count=50
                    )
                    for key in keys:
                        raw = await r.get(key)
                        if raw:
                            data = json.loads(raw)
                            intent_name = key.split(":intent:")[-1] if ":intent:" in key else key.split(":")[-1]
                            bypassed = int(data.get("bypassed_count", 0))
                            avg_cost = data.get("avg_cost_when_forwarded", {}).get("value", 0.0)
                            bypass_rate = data.get("bypass_success_rate", {}).get("value", 0.0)
                            intent_entries.append({
                                "intent": intent_name,
                                "bypassed": bypassed,
                                "cost_avoided": bypassed * float(avg_cost),
                                "bypass_accuracy": float(bypass_rate),
                            })
                    if cursor == 0:
                        break

                if intent_entries:
                    if "intent_memory" not in data_sources:
                        data_sources.append("intent_memory")
                    limitations.append(
                        "Intent memory é cumulativa (all-time) — não filtrada pela janela de "
                        "tempo selecionada."
                    )
                    for entry in sorted(
                        intent_entries, key=lambda x: x["cost_avoided"], reverse=True
                    )[:10]:
                        top_intents.append(GainIntentBreakdown(
                            intent=entry["intent"],
                            calls_avoided=entry["bypassed"],
                            cost_avoided_usd=entry["cost_avoided"],
                            bypass_accuracy=entry["bypass_accuracy"],
                            source="intent_memory_cumulative",
                        ))
            except Exception:
                logger.debug("gain_report: intent memory scan failed", exc_info=True)

        # ── 6. Top models ─────────────────────────────────────────────────────
        top_models = [
            GainModelBreakdown(
                model_used=model,
                calls_routed=agg["calls_routed"],
                cost_avoided_usd=agg["cost_avoided_usd"],
            )
            for model, agg in sorted(
                models_agg.items(), key=lambda x: x[1]["cost_avoided_usd"], reverse=True
            )[:10]
            if agg["cost_avoided_usd"] > 0
        ]

        # ── 7. Top strategies ─────────────────────────────────────────────────
        cache_hits = 0
        cache_cost = 0.0
        policy_bypasses = 0
        policy_cost = 0.0

        for e in windowed_events:
            decision = e.get("decision", "")
            decision_source = (e.get("metadata") or {}).get("decision_source", "")
            cost_saved = float(e.get("cost_saved", 0.0))
            if decision_source == "cache":
                cache_hits += 1
                cache_cost += cost_saved
            elif decision == "bypass":
                policy_bypasses += 1
                policy_cost += cost_saved

        model_downgrade_count = sum(
            agg["calls_routed"] for agg in models_agg.values() if agg["cost_avoided_usd"] > 0
        )
        model_downgrade_cost = sum(
            agg["cost_avoided_usd"] for agg in models_agg.values() if agg["cost_avoided_usd"] > 0
        )

        top_strategies: list[GainStrategyBreakdown] = [
            GainStrategyBreakdown(
                strategy="cache_hit",
                label="Cache de decisão",
                count=cache_hits,
                cost_avoided_usd=cache_cost,
            ),
            GainStrategyBreakdown(
                strategy="policy_bypass",
                label="Bypass por política",
                count=policy_bypasses,
                cost_avoided_usd=policy_cost,
            ),
            GainStrategyBreakdown(
                strategy="compression",
                label="Compressão de prompt (METIS)",
                count=metis_total,
                cost_avoided_usd=0.0,   # hard to isolate LLM cost from token reduction alone
            ),
            GainStrategyBreakdown(
                strategy="model_downgrade",
                label="Roteamento para modelo mais eficiente",
                count=model_downgrade_count,
                cost_avoided_usd=model_downgrade_cost,
            ),
        ]

        # ── 8. Top saving drivers (intent proxy — PolicyStats not in Redis v0) ─
        top_saving_drivers: list[GainSavingDriver] = []
        for intent_bd in top_intents[:10]:
            # Denominator is the total estimated savings, not the intent subtotal,
            # so the percentage is meaningful relative to the headline figure.
            pct = (
                intent_bd.cost_avoided_usd / estimated_cost_avoided * 100
                if estimated_cost_avoided > 0 else 0.0
            )
            top_saving_drivers.append(GainSavingDriver(
                name=intent_bd.intent,
                calls_avoided=intent_bd.calls_avoided,
                cost_avoided_usd=intent_bd.cost_avoided_usd,
                pct_of_total_savings=pct,
                source="intent_bypass_proxy",
                is_estimated=True,
            ))
        if top_saving_drivers:
            limitations.append(
                "Drivers de economia estimados via bypass de intent — "
                "PolicyStats ainda não persistidos no Redis (v0 limitation)."
            )

        # ── 9. Confidence ─────────────────────────────────────────────────────
        # "windowed" means data is filtered to the requested time window.
        # Cumulative-only fallback is never promoted above "low" regardless of volume.
        has_windowed_data = "economics_bucket" in data_sources or "telemetry_events" in data_sources
        if total_requests >= 100 and economics_days >= 7:
            confidence = "high"
        elif total_requests >= 20 and has_windowed_data:
            confidence = "medium"
        else:
            confidence = "low"
            if total_requests < 20:
                limitations.append(
                    f"Apenas {total_requests} requisições na janela selecionada — "
                    "aguardando volume mínimo de 20 para confiança média."
                )
            elif not has_windowed_data:
                limitations.append(
                    "Dados disponíveis são cumulativos (all-time) — "
                    "não filtrados pela janela de tempo selecionada."
                )

        llm_pct = llm_calls_avoided / total_requests if total_requests > 0 else 0.0

        return AionGainReport(
            schema_version=_SCHEMA_VERSION,
            window_start=from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            window_end=to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            total_requests=total_requests,
            llm_calls_avoided=llm_calls_avoided,
            llm_calls_avoided_pct=llm_pct,
            tokens_saved=tokens_saved,
            estimated_cost_avoided_usd=estimated_cost_avoided,
            estimated_latency_avoided_ms=estimated_latency_ms,
            top_saving_drivers=top_saving_drivers,
            top_intents=top_intents,
            top_models=top_models,
            top_strategies=top_strategies,
            confidence=confidence,
            limitations=limitations,
            data_sources=data_sources,
            calculation_notes=calculation_notes,
            generated_at=generated_at,
        )
