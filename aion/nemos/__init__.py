"""NEMOS — Mnemosyne: the memory of AION.

Shared intelligence layer consumed and produced by ESTIXE, NOMOS, and METIS.
Each module is autonomous — reads what exists, ignores what doesn't.

Architecture rules:
1. No module requires another module to be active
2. Cross-module learning happens exclusively via NEMOS signals
3. Every reader accepts absence gracefully (falls back to defaults)
4. All writes are async / fire-and-forget (0ms on response path)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from aion.nemos.baseline import TenantBaseline
from aion.nemos.economics import EconomicsBucket
from aion.nemos.guard import ActuationGuard, GuardRegistry
from aion.nemos.models import (
    DecisionConfidence,
    EconomicSignals,
    IntentMemory,
    ModelPerformance,
    OptimizationMemory,
    OutcomeRecord,
    PolicyStats,
)
from aion.nemos.recommendations import Recommendation, generate_recommendations
from aion.nemos.store import NemosStore

logger = logging.getLogger("aion.nemos")

_MEMORY_TTL = 30 * 86400       # 30 days
_DAILY_ECON_TTL = 30 * 86400   # 30 days
_WEEKLY_ECON_TTL = 90 * 86400  # 90 days
_SNAPSHOT_TTL = 90 * 86400     # 90 days


class Nemos:
    """Facade for all NEMOS operations. Thin orchestrator — logic lives in sub-modules."""

    def __init__(self) -> None:
        self._store = NemosStore(local_maxlen=1000)
        self._guards = GuardRegistry()
        # In-memory caches (populated on read, bounded)
        self._baselines: dict[str, TenantBaseline] = {}
        self._economics: dict[str, EconomicsBucket] = {}

    # ══════════════════════════════════════════════
    # NOMOS: Decision Memory
    # ══════════════════════════════════════════════

    async def record_outcome(self, record: OutcomeRecord) -> None:
        """Record a routing outcome. Updates ModelPerformance aggregates."""
        tier = _complexity_tier(record.complexity_score)
        key = f"aion:memory:{record.tenant}:{record.model}"

        # Load or create performance
        perf = await self._load_model_performance(record.tenant, record.model)
        perf.record(tier, record.detected_intent, record.actual_latency_ms,
                    record.actual_cost, record.success)

        # Persist
        await self._store.set_json(key, perf.to_dict(), ttl_seconds=_MEMORY_TTL)

    async def get_model_performances(self, tenant: str) -> dict[str, ModelPerformance]:
        """Get all model performances for a tenant. Returns empty dict if none."""
        keys = await self._store.keys_by_prefix(f"aion:memory:{tenant}:")
        result: dict[str, ModelPerformance] = {}
        for key in keys:
            # Skip sub-keys (complexity tiers, intents)
            parts = key.split(":")
            if len(parts) != 4:  # aion:memory:{tenant}:{model}
                continue
            model = parts[3]
            perf = await self._load_model_performance(tenant, model)
            if perf.request_count > 0:
                result[model] = perf
        return result

    async def get_economic_signals(self, tenant: str) -> EconomicSignals:
        """Derive economic signals from accumulated data."""
        signals = EconomicSignals()
        perfs = await self.get_model_performances(tenant)
        for model, perf in perfs.items():
            if perf.request_count < 10:
                continue
            # Cost correction: avg actual cost vs what the model estimates
            for tier_name, tier_stats in perf.by_complexity.items():
                if tier_stats.count >= 5 and tier_stats.avg_cost.value > 0:
                    signals.model_cost_correction[model] = max(0.5, min(2.0,
                        tier_stats.avg_cost.value / max(0.0001, tier_stats.avg_cost.value)
                    ))
                    break
        return signals

    async def _load_model_performance(self, tenant: str, model: str) -> ModelPerformance:
        key = f"aion:memory:{tenant}:{model}"
        data = await self._store.get_json(key)
        if data:
            return _deserialize_model_perf(data, tenant, model)
        return ModelPerformance(model=model, tenant=tenant)

    # ══════════════════════════════════════════════
    # ESTIXE: Intent & Policy Intelligence
    # ══════════════════════════════════════════════

    async def record_estixe_outcome(
        self, tenant: str, intent: str, decision: str,
        was_correct: bool, cost_if_forwarded: float,
    ) -> None:
        if not intent:
            return
        key = f"aion:estixe:{tenant}:intent:{intent}"
        mem = await self._load_intent_memory(tenant, intent)

        if decision == "bypass":
            mem.record_bypass(was_correct)
        else:
            mem.record_forward(cost_if_forwarded, had_followup=not was_correct)

        await self._store.set_json(key, mem.to_dict(), ttl_seconds=_MEMORY_TTL)

    async def get_intent_memory(self, tenant: str) -> dict[str, IntentMemory]:
        keys = await self._store.keys_by_prefix(f"aion:estixe:{tenant}:intent:")
        result: dict[str, IntentMemory] = {}
        for key in keys:
            intent = key.split(":")[-1]
            mem = await self._load_intent_memory(tenant, intent)
            if mem.total_seen > 0:
                result[intent] = mem
        return result

    async def _load_intent_memory(self, tenant: str, intent: str) -> IntentMemory:
        key = f"aion:estixe:{tenant}:intent:{intent}"
        data = await self._store.get_json(key)
        if data:
            return _deserialize_intent_memory(data)
        return IntentMemory(intent=intent)

    async def get_policy_effectiveness(self, tenant: str) -> dict[str, PolicyStats]:
        keys = await self._store.keys_by_prefix(f"aion:estixe:{tenant}:policy:")
        result: dict[str, PolicyStats] = {}
        for key in keys:
            policy_name = key.split(":")[-1]
            data = await self._store.get_json(key)
            if data:
                result[policy_name] = PolicyStats(
                    policy_name=policy_name,
                    times_triggered=data.get("times_triggered", 0),
                )
        return result

    # ══════════════════════════════════════════════
    # METIS: Optimization Intelligence
    # ══════════════════════════════════════════════

    async def record_metis_outcome(
        self, tenant: str, tokens_before: int, tokens_after: int,
        compression_applied: bool, had_followup: bool,
    ) -> None:
        key = f"aion:metis:{tenant}:optimization"
        mem = await self._load_optimization_memory(tenant)
        mem.record(tokens_before, tokens_after, compression_applied, had_followup)
        await self._store.set_json(key, mem.to_dict(), ttl_seconds=_MEMORY_TTL)

    async def get_optimization_memory(self, tenant: str) -> OptimizationMemory | None:
        mem = await self._load_optimization_memory(tenant)
        return mem if mem.total > 0 else None

    async def _load_optimization_memory(self, tenant: str) -> OptimizationMemory:
        key = f"aion:metis:{tenant}:optimization"
        data = await self._store.get_json(key)
        if data:
            return _deserialize_optimization_memory(data, tenant)
        return OptimizationMemory(tenant=tenant)

    # ══════════════════════════════════════════════
    # Economics
    # ══════════════════════════════════════════════

    async def record_economics(
        self, tenant: str, model: str, intent: str, decision: str,
        actual_cost: float, default_cost: float, tokens: int, latency_ms: float,
    ) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"aion:econ:{tenant}:daily:{today}"

        bucket = self._economics.get(key)
        if not bucket:
            bucket = EconomicsBucket(tenant=tenant, period=today)
            self._economics[key] = bucket
            # Bound cache
            if len(self._economics) > 100:
                oldest = next(iter(self._economics))
                del self._economics[oldest]

        bucket.record(model, intent, decision, actual_cost, default_cost, tokens, latency_ms)
        await self._store.set_json(key, bucket.to_dict(), ttl_seconds=_DAILY_ECON_TTL)

    async def get_economics(self, tenant: str, period: str | None = None) -> dict | None:
        if period:
            key = f"aion:econ:{tenant}:daily:{period}"
            return await self._store.get_json(key)
        # Return today's bucket
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"aion:econ:{tenant}:daily:{today}"
        return await self._store.get_json(key)

    # ══════════════════════════════════════════════
    # Baseline
    # ══════════════════════════════════════════════

    async def update_baseline(
        self, tenant: str, latency_ms: float, cost: float, tokens: int,
        model: str, intent: str, complexity_tier: str, decision: str,
    ) -> None:
        baseline = self._baselines.get(tenant)
        if not baseline:
            data = await self._store.get_json(f"aion:baseline:{tenant}")
            baseline = _deserialize_baseline(data, tenant) if data else TenantBaseline(tenant=tenant)
            self._baselines[tenant] = baseline

        baseline.record(latency_ms, cost, tokens, model, intent, complexity_tier, decision)
        await self._store.set_json(f"aion:baseline:{tenant}", baseline.to_dict())

    async def get_baseline(self, tenant: str) -> TenantBaseline | None:
        if tenant in self._baselines and self._baselines[tenant].total_requests > 0:
            return self._baselines[tenant]
        data = await self._store.get_json(f"aion:baseline:{tenant}")
        if data:
            baseline = _deserialize_baseline(data, tenant)
            self._baselines[tenant] = baseline
            return baseline
        return None

    async def snapshot_baselines_if_needed(self) -> None:
        """Take daily snapshot of all baselines for trend computation."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for tenant, baseline in self._baselines.items():
            if baseline.total_requests < 10:
                continue
            snapshot_key = f"aion:baseline:{tenant}:snapshots:{today}"
            existing = await self._store.get_json(snapshot_key)
            if not existing:
                await self._store.set_json(snapshot_key, baseline.snapshot(), ttl_seconds=_SNAPSHOT_TTL)

    async def get_baseline_trends(self, tenant: str) -> dict:
        """Compare current baseline vs historical snapshots."""
        baseline = await self.get_baseline(tenant)
        if not baseline:
            return {}

        trends = {}
        now = datetime.now(timezone.utc)
        for label, days_ago in [("vs_yesterday", 1), ("vs_last_week", 7), ("vs_last_month", 30)]:
            from datetime import timedelta
            target_date = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            snapshot_key = f"aion:baseline:{tenant}:snapshots:{target_date}"
            snapshot = await self._store.get_json(snapshot_key)
            if snapshot:
                trends[label] = {
                    "latency_delta_pct": _pct_change(snapshot.get("avg_latency_ms", 0), baseline.avg_latency_ms.value),
                    "cost_delta_pct": _pct_change(snapshot.get("avg_cost_per_request", 0), baseline.avg_cost_per_request.value),
                }
        return trends

    # ══════════════════════════════════════════════
    # Recommendations
    # ══════════════════════════════════════════════

    async def get_recommendations(self, tenant: str) -> list[Recommendation]:
        intents = await self.get_intent_memory(tenant)
        perfs = await self.get_model_performances(tenant)
        opt_mem = await self.get_optimization_memory(tenant)
        recs = generate_recommendations(tenant, intents, perfs, opt_mem)

        # Add rollback notifications
        for guard in self._guards.active_guards():
            if guard.get("rolled_back") and guard.get("tenant") == tenant:
                recs.append(Recommendation(
                    type="auto_rollback",
                    confidence="high",
                    reason=f"Auto-actuation '{guard['actuation_type']}' on {guard['module']}/{guard['param_name']} "
                           f"was rolled back (metric degraded). Value reverted from {guard['value_after']:.4f} to {guard['value_before']:.4f}.",
                    details=guard,
                ))

        return recs

    # ══════════════════════════════════════════════
    # Actuation Guards
    # ══════════════════════════════════════════════

    @property
    def guards(self) -> GuardRegistry:
        return self._guards

    # ══════════════════════════════════════════════
    # Module Maturity
    # ══════════════════════════════════════════════

    async def get_module_maturity(self, tenant: str) -> dict[str, dict]:
        """Get maturity state for each module for a tenant."""
        result = {}
        # NOMOS
        perfs = await self.get_model_performances(tenant)
        nomos_points = sum(p.request_count for p in perfs.values())
        result["nomos"] = {"state": _maturity_label(nomos_points), "data_points": nomos_points}

        # ESTIXE
        intents = await self.get_intent_memory(tenant)
        estixe_points = sum(m.total_seen for m in intents.values())
        result["estixe"] = {"state": _maturity_label(estixe_points), "data_points": estixe_points}

        # METIS
        opt = await self.get_optimization_memory(tenant)
        metis_points = opt.total if opt else 0
        result["metis"] = {"state": _maturity_label(metis_points), "data_points": metis_points}

        return result

    async def get_operating_mode(self, tenant: str) -> str:
        """Derive operating_mode for a tenant from baseline + maturity.

        Returns one of: stateless | learning | adaptive | stabilized.
        - stateless  : no data or Redis absent
        - learning   : <100 requests total
        - adaptive   : stable baseline, learned data active
        - stabilized : stable baseline, no drift in last 24h
        """
        baseline = await self.get_baseline(tenant)
        if not baseline or baseline.total_requests == 0:
            return "stateless"
        if baseline.total_requests < 100:
            return "learning"
        if getattr(baseline, "drift_detected", False):
            return "adaptive"
        return "stabilized"

    # ══════════════════════════════════════════════
    # LGPD
    # ══════════════════════════════════════════════

    async def delete_tenant_data(self, tenant: str) -> int:
        """Delete all NEMOS data for a tenant. LGPD compliance."""
        deleted = 0
        deleted += await self._store.delete_pattern(f"aion:memory:{tenant}:*")
        deleted += await self._store.delete_pattern(f"aion:estixe:{tenant}:*")
        deleted += await self._store.delete_pattern(f"aion:metis:{tenant}:*")
        deleted += await self._store.delete_pattern(f"aion:econ:{tenant}:*")
        deleted += await self._store.delete_pattern(f"aion:baseline:{tenant}*")
        self._baselines.pop(tenant, None)
        logger.info("NEMOS: deleted %d keys for tenant '%s' (LGPD)", deleted, tenant)
        return deleted


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def _complexity_tier(score: float) -> str:
    if score < 30:
        return "simple"
    if score < 60:
        return "medium"
    return "complex"


def _maturity_label(count: int) -> str:
    if count < 20:
        return "cold"
    if count < 100:
        return "warm"
    return "stable"


def _pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return round(((new - old) / old) * 100, 1)


def _deserialize_model_perf(data: dict, tenant: str, model: str) -> ModelPerformance:
    from aion.nemos.ema import TierStats
    perf = ModelPerformance(
        model=model, tenant=tenant,
        request_count=data.get("request_count", 0),
        success_count=data.get("success_count", 0),
        failure_count=data.get("failure_count", 0),
        updated_at=data.get("updated_at", 0),
    )
    for tier_name, tier_data in data.get("by_complexity", {}).items():
        perf.by_complexity[tier_name] = TierStats.from_dict(tier_data)
    for intent, intent_data in data.get("by_intent", {}).items():
        perf.by_intent[intent] = TierStats.from_dict(intent_data)
    return perf


def _deserialize_intent_memory(data: dict) -> IntentMemory:
    from aion.nemos.ema import DecayedEMA
    return IntentMemory(
        intent=data.get("intent", ""),
        total_seen=data.get("total_seen", 0),
        bypassed_count=data.get("bypassed_count", 0),
        forwarded_count=data.get("forwarded_count", 0),
        bypass_success_rate=DecayedEMA.from_dict(data.get("bypass_success_rate", {"value": 1.0})),
        avg_cost_when_forwarded=DecayedEMA.from_dict(data.get("avg_cost_when_forwarded", {})),
        followup_rate=DecayedEMA.from_dict(data.get("followup_rate", {})),
    )


def _deserialize_optimization_memory(data: dict, tenant: str) -> OptimizationMemory:
    from aion.nemos.ema import DecayedEMA
    return OptimizationMemory(
        tenant=tenant,
        total=data.get("total", 0),
        compression_effectiveness=DecayedEMA.from_dict(data.get("compression_effectiveness", {})),
        avg_tokens_saved=DecayedEMA.from_dict(data.get("avg_tokens_saved", {})),
        followup_rate_compressed=DecayedEMA.from_dict(data.get("followup_rate_compressed", {})),
        followup_rate_uncompressed=DecayedEMA.from_dict(data.get("followup_rate_uncompressed", {})),
    )


def _deserialize_baseline(data: dict, tenant: str) -> TenantBaseline:
    from aion.nemos.ema import DecayedEMA
    return TenantBaseline(
        tenant=tenant,
        total_requests=data.get("total_requests", 0),
        avg_latency_ms=DecayedEMA(value=data.get("avg_latency_ms", 0)),
        avg_cost_per_request=DecayedEMA(value=data.get("avg_cost_per_request", 0)),
        avg_tokens_per_request=DecayedEMA(value=data.get("avg_tokens_per_request", 0)),
        bypass_rate=DecayedEMA(value=data.get("bypass_rate", 0)),
        block_rate=DecayedEMA(value=data.get("block_rate", 0)),
        model_counts=data.get("model_distribution", {}),
        intent_counts=data.get("intent_distribution", {}),
        complexity_counts=data.get("complexity_distribution", {}),
        first_seen=data.get("first_seen", 0),
        last_updated=data.get("last_updated", 0),
    )


# ── Singleton ──
_instance: Nemos | None = None


def get_nemos() -> Nemos:
    global _instance
    if _instance is None:
        _instance = Nemos()
    return _instance
