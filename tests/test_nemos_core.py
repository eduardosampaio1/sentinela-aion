"""Tests for NEMOS — the memory layer of AION.

Covers: DecayedEMA, ModelPerformance, IntentMemory, OptimizationMemory,
TenantBaseline, EconomicsBucket, ActuationGuard, Recommendations, Nemos facade.
"""

from __future__ import annotations

import time

import pytest

from aion.nemos.ema import (
    DecayedEMA,
    SignalConfidence,
    TierStats,
    confidence_from_count,
    confidence_weight,
    maturity_from_count,
    ModuleMaturityState,
)
from aion.nemos.models import (
    DecisionConfidence,
    EconomicSignals,
    IntentMemory,
    ModelPerformance,
    OptimizationMemory,
    OutcomeRecord,
)
from aion.nemos.baseline import TenantBaseline
from aion.nemos.economics import EconomicsBucket
from aion.nemos.guard import ActuationGuard, GuardRegistry
from aion.nemos.recommendations import Recommendation, generate_recommendations


# ══════════════════════════════════════════════
# DecayedEMA
# ══════════════════════════════════════════════

class TestDecayedEMA:
    def test_first_value_seeds(self):
        ema = DecayedEMA()
        ema.update(100.0, now=1000.0)
        assert ema.value == 100.0
        assert ema.count == 1

    def test_converges_toward_new_values(self):
        ema = DecayedEMA()
        for i in range(50):
            ema.update(10.0, now=1000.0 + i)
        # After many updates of 10.0, should be close to 10
        assert abs(ema.value - 10.0) < 1.0

    def test_decay_reduces_old_value(self):
        ema = DecayedEMA(half_life_hours=1.0)
        ema.update(100.0, now=0)
        # After 1 hour (half-life), update with 0 — value should drop significantly
        ema.update(0.0, now=3600)
        assert ema.value < 100.0  # decayed from 100

    def test_adaptive_alpha_high_when_cold(self):
        ema = DecayedEMA()
        ema.update(100.0, now=0)
        ema.update(0.0, now=1)
        # With only 2 data points, alpha=0.3 → value shifts 30% toward 0
        assert ema.value == pytest.approx(70.0, abs=1.0)

    def test_adaptive_alpha_low_when_stable(self):
        ema = DecayedEMA()
        now = 0.0
        for i in range(200):
            ema.update(100.0, now=now)
            now += 1
        # After 200 updates, alpha is low — one outlier barely moves the mean
        ema.update(0.0, now=now)
        assert ema.value > 90.0

    def test_serialization_roundtrip(self):
        ema = DecayedEMA(value=42.5, count=10, last_update=1000.0)
        d = ema.to_dict()
        restored = DecayedEMA.from_dict(d)
        assert restored.value == 42.5
        assert restored.count == 10

    def test_confidence_from_count(self):
        assert confidence_from_count(0) == SignalConfidence.NONE
        assert confidence_from_count(5) == SignalConfidence.LOW
        assert confidence_from_count(50) == SignalConfidence.MEDIUM
        assert confidence_from_count(200) == SignalConfidence.HIGH

    def test_confidence_weight(self):
        assert confidence_weight(SignalConfidence.NONE) == 0.0
        assert confidence_weight(SignalConfidence.LOW) == 0.0
        assert confidence_weight(SignalConfidence.MEDIUM) == 0.5
        assert confidence_weight(SignalConfidence.HIGH) == 1.0


# ══════════════════════════════════════════════
# TierStats
# ══════════════════════════════════════════════

class TestTierStats:
    def test_record_updates_all_fields(self):
        ts = TierStats()
        ts.record(100.0, 0.01, True, now=1000.0)
        assert ts.count == 1
        assert ts.avg_latency.value == 100.0
        assert ts.avg_cost.value == 0.01
        assert ts.success_rate.value == 1.0

    def test_failure_reduces_success_rate(self):
        ts = TierStats()
        for _ in range(10):
            ts.record(100.0, 0.01, True, now=1000.0)
        ts.record(100.0, 0.01, False, now=1001.0)
        assert ts.success_rate.value < 1.0


# ══════════════════════════════════════════════
# ModelPerformance
# ══════════════════════════════════════════════

class TestModelPerformance:
    def test_record_increments_counts(self):
        perf = ModelPerformance(model="gpt-4o", tenant="test")
        perf.record("simple", "greeting", 100.0, 0.01, True)
        assert perf.request_count == 1
        assert perf.success_count == 1
        assert "simple" in perf.by_complexity

    def test_intent_bounded_at_50(self):
        perf = ModelPerformance(model="gpt-4o", tenant="test")
        for i in range(60):
            perf.record("simple", f"intent_{i}", 100.0, 0.01, True)
        assert len(perf.by_intent) == 50

    def test_maturity_states(self):
        perf = ModelPerformance(model="gpt-4o", tenant="test")
        assert perf.maturity == ModuleMaturityState.COLD
        for _ in range(25):
            perf.record("simple", "x", 100.0, 0.01, True)
        assert perf.maturity == ModuleMaturityState.WARM
        for _ in range(80):
            perf.record("simple", "x", 100.0, 0.01, True)
        assert perf.maturity == ModuleMaturityState.STABLE


# ══════════════════════════════════════════════
# IntentMemory
# ══════════════════════════════════════════════

class TestIntentMemory:
    def test_bypass_tracking(self):
        mem = IntentMemory(intent="greeting")
        for _ in range(10):
            mem.record_bypass(was_correct=True)
        assert mem.total_seen == 10
        assert mem.bypassed_count == 10
        assert mem.bypass_success_rate.value > 0.9

    def test_forward_tracking(self):
        mem = IntentMemory(intent="question")
        mem.record_forward(cost=0.005, had_followup=False)
        assert mem.total_seen == 1
        assert mem.forwarded_count == 1

    def test_bypass_failure_reduces_rate(self):
        mem = IntentMemory(intent="greeting")
        for _ in range(10):
            mem.record_bypass(was_correct=True)
        for _ in range(5):
            mem.record_bypass(was_correct=False)
        assert mem.bypass_success_rate.value < 0.95


# ══════════════════════════════════════════════
# OptimizationMemory
# ══════════════════════════════════════════════

class TestOptimizationMemory:
    def test_compression_tracking(self):
        mem = OptimizationMemory(tenant="test")
        mem.record(100, 70, compression_applied=True, had_followup=False)
        assert mem.total == 1
        assert mem.avg_tokens_saved.value == 30

    def test_followup_rates_separated(self):
        mem = OptimizationMemory(tenant="test")
        mem.record(100, 70, compression_applied=True, had_followup=True)
        mem.record(100, 100, compression_applied=False, had_followup=False)
        assert mem.followup_rate_compressed.value > 0.5
        assert mem.followup_rate_uncompressed.value < 0.5


# ══════════════════════════════════════════════
# TenantBaseline
# ══════════════════════════════════════════════

class TestTenantBaseline:
    def test_record_updates_baseline(self):
        bl = TenantBaseline(tenant="test")
        bl.record(100.0, 0.01, 500, "gpt-4o", "greeting", "simple", "continue")
        assert bl.total_requests == 1
        assert bl.avg_latency_ms.value == 100.0

    def test_maturity_progression(self):
        bl = TenantBaseline(tenant="test")
        assert bl.maturity == "cold"
        for _ in range(25):
            bl.record(100.0, 0.01, 500, "gpt-4o", "q", "simple", "continue")
        assert bl.maturity == "warm"
        for _ in range(80):
            bl.record(100.0, 0.01, 500, "gpt-4o", "q", "simple", "continue")
        assert bl.maturity == "stable"

    def test_model_distribution(self):
        bl = TenantBaseline(tenant="test")
        for _ in range(3):
            bl.record(100.0, 0.01, 500, "gpt-4o-mini", "q", "simple", "continue")
        bl.record(100.0, 0.01, 500, "gpt-4o", "q", "medium", "continue")
        dist = bl._distribution(bl.model_counts)
        assert dist["gpt-4o-mini"] == 0.75
        assert dist["gpt-4o"] == 0.25


# ══════════════════════════════════════════════
# EconomicsBucket
# ══════════════════════════════════════════════

class TestEconomicsBucket:
    def test_record_aggregates(self):
        bucket = EconomicsBucket(tenant="test", period="2026-04-14")
        bucket.record("gpt-4o-mini", "greeting", "bypass", 0.0, 0.005, 0, 0)
        bucket.record("gpt-4o", "analysis", "continue", 0.02, 0.02, 800, 500)
        assert bucket.total_requests == 2
        assert bucket.total_savings > 0

    def test_model_breakdown(self):
        bucket = EconomicsBucket(tenant="test", period="2026-04-14")
        bucket.record("gpt-4o-mini", "q", "continue", 0.001, 0.01, 500, 200)
        d = bucket.to_dict()
        assert "gpt-4o-mini" in d["by_model"]


# ══════════════════════════════════════════════
# ActuationGuard
# ══════════════════════════════════════════════

class TestActuationGuard:
    def test_observe_within_window_returns_none(self):
        guard = ActuationGuard(
            actuation_type="threshold_adjust", tenant="test", module="estixe",
            param_name="threshold", value_before=0.85, value_after=0.80,
            metric_before=0.05, window_requests=10,
        )
        result = guard.observe(0.05)
        assert result is None  # still observing

    def test_no_degradation_keeps_actuation(self):
        guard = ActuationGuard(
            actuation_type="threshold_adjust", tenant="test", module="estixe",
            param_name="threshold", value_before=0.85, value_after=0.80,
            metric_before=0.10, window_requests=5,
        )
        for _ in range(5):
            result = guard.observe(0.10)
        assert result is False  # kept

    def test_degradation_triggers_rollback(self):
        guard = ActuationGuard(
            actuation_type="threshold_adjust", tenant="test", module="estixe",
            param_name="threshold", value_before=0.85, value_after=0.80,
            metric_before=0.10, window_requests=5, rollback_threshold=0.10,
        )
        for _ in range(4):
            guard.observe(0.15)
        result = guard.observe(0.15)
        assert result is True  # rolled back
        assert guard.rolled_back

    def test_cooldown_after_rollback(self):
        guard = ActuationGuard(
            actuation_type="test", tenant="t", module="m",
            param_name="p", value_before=1.0, value_after=2.0,
            metric_before=0.10, window_requests=2, cooldown_requests=3,
        )
        guard.observe(0.20)
        guard.observe(0.20)  # triggers rollback
        assert guard.in_cooldown
        assert guard.cooldown_remaining == 3
        guard.observe(0.10)  # cooldown tick
        assert guard.cooldown_remaining == 2


class TestGuardRegistry:
    def test_register_and_get(self):
        reg = GuardRegistry()
        guard = ActuationGuard(
            actuation_type="test", tenant="t", module="m",
            param_name="p", value_before=1.0, value_after=2.0, metric_before=0.1,
        )
        reg.register(guard)
        assert reg.get("t", "m", "p") is guard

    def test_cooldown_check(self):
        reg = GuardRegistry()
        guard = ActuationGuard(
            actuation_type="test", tenant="t", module="m",
            param_name="p", value_before=1.0, value_after=2.0,
            metric_before=0.1, window_requests=1, cooldown_requests=5,
        )
        reg.register(guard)
        assert not reg.is_in_cooldown("t", "m", "p")
        guard.observe(0.50)  # triggers rollback
        assert reg.is_in_cooldown("t", "m", "p")


# ══════════════════════════════════════════════
# Recommendations
# ══════════════════════════════════════════════

class TestRecommendations:
    def test_bypass_candidate(self):
        intents = {
            "greeting": IntentMemory(
                intent="greeting", total_seen=50, bypassed_count=5, forwarded_count=45,
            ),
        }
        # Set high success rate and cost
        intents["greeting"].bypass_success_rate.value = 0.98
        intents["greeting"].bypass_success_rate.count = 50
        intents["greeting"].avg_cost_when_forwarded.value = 0.005
        intents["greeting"].avg_cost_when_forwarded.count = 50

        recs = generate_recommendations("test", intents, {}, None)
        assert any(r.type == "bypass_candidate" for r in recs)

    def test_no_recs_when_low_confidence(self):
        intents = {
            "greeting": IntentMemory(intent="greeting", total_seen=5),
        }
        recs = generate_recommendations("test", intents, {}, None)
        assert len(recs) == 0


# ══════════════════════════════════════════════
# Nemos Facade (async)
# ══════════════════════════════════════════════

class TestNemosFacade:
    @pytest.mark.asyncio
    async def test_record_and_get_outcome(self):
        from aion.nemos import Nemos
        nemos = Nemos()

        record = OutcomeRecord(
            request_id="test-1", tenant="acme", timestamp=time.time(),
            model="gpt-4o-mini", provider="openai", complexity_score=25.0,
            detected_intent="greeting", estimated_cost=0.001, actual_cost=0.0008,
            actual_latency_ms=150.0, actual_prompt_tokens=100, actual_completion_tokens=50,
            success=True, route_reason="simple", decision="continue",
        )
        await nemos.record_outcome(record)
        perfs = await nemos.get_model_performances("acme")
        assert "gpt-4o-mini" in perfs
        assert perfs["gpt-4o-mini"].request_count == 1

    @pytest.mark.asyncio
    async def test_record_estixe_outcome(self):
        from aion.nemos import Nemos
        nemos = Nemos()
        await nemos.record_estixe_outcome("acme", "greeting", "bypass", True, 0.005)
        intents = await nemos.get_intent_memory("acme")
        assert "greeting" in intents
        assert intents["greeting"].bypassed_count == 1

    @pytest.mark.asyncio
    async def test_record_metis_outcome(self):
        from aion.nemos import Nemos
        nemos = Nemos()
        await nemos.record_metis_outcome("acme", 100, 70, True, False)
        mem = await nemos.get_optimization_memory("acme")
        assert mem is not None
        assert mem.total == 1

    @pytest.mark.asyncio
    async def test_baseline_updates(self):
        from aion.nemos import Nemos
        nemos = Nemos()
        await nemos.update_baseline("acme", 100.0, 0.01, 500, "gpt-4o", "q", "simple", "continue")
        bl = await nemos.get_baseline("acme")
        assert bl is not None
        assert bl.total_requests == 1

    @pytest.mark.asyncio
    async def test_delete_tenant_data(self):
        from aion.nemos import Nemos
        nemos = Nemos()
        await nemos.update_baseline("del-me", 100.0, 0.01, 500, "gpt-4o", "q", "simple", "continue")
        deleted = await nemos.delete_tenant_data("del-me")
        bl = await nemos.get_baseline("del-me")
        assert bl is None

    @pytest.mark.asyncio
    async def test_module_maturity(self):
        from aion.nemos import Nemos
        nemos = Nemos()
        mat = await nemos.get_module_maturity("empty-tenant")
        assert mat["nomos"]["state"] == "cold"
        assert mat["estixe"]["state"] == "cold"
        assert mat["metis"]["state"] == "cold"

    @pytest.mark.asyncio
    async def test_economics_recording(self):
        from aion.nemos import Nemos
        nemos = Nemos()
        await nemos.record_economics("acme", "gpt-4o-mini", "greeting", "bypass", 0.0, 0.005, 0, 0)
        econ = await nemos.get_economics("acme")
        assert econ is not None

    @pytest.mark.asyncio
    async def test_recommendations_empty_when_cold(self):
        from aion.nemos import Nemos
        nemos = Nemos()
        recs = await nemos.get_recommendations("cold-tenant")
        assert isinstance(recs, list)
