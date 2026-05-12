"""Unit tests for aion/kairos/shadow.py — Fase 4: Shadow Evaluator.

Tests cover:
- _extract_context_value(): all PipelineContext field mappings
- _evaluate_condition(): all 7 operators, None actual, evaluation errors
- _candidate_matches(): empty conditions, all-match, one-fails
- KairosShadowEvaluator.evaluate(): KAIROS disabled, no tenant, list errors, happy path
- KairosShadowEvaluator._observe(): all early-exit paths, matched/unmatched counters
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aion.kairos.models import (
    PolicyCandidate,
    PolicyCandidateStatus,
    ShadowRun,
    ShadowRunStatus,
    TriggerCondition,
)
from aion.kairos.shadow import (
    KairosShadowEvaluator,
    _candidate_matches,
    _evaluate_condition,
    _extract_context_value,
)
from aion.shared.schemas import Decision, PipelineContext


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ctx(**kwargs) -> PipelineContext:
    defaults = {"tenant": "tenant-x", "metadata": {}}
    defaults.update(kwargs)
    return PipelineContext(**defaults)


def _condition(field: str, operator: str, value) -> TriggerCondition:
    return TriggerCondition(field=field, operator=operator, value=value)


def _candidate(
    status: PolicyCandidateStatus = PolicyCandidateStatus.SHADOW_RUNNING,
    conditions: list[TriggerCondition] | None = None,
    shadow_run_id: str | None = None,
    **kwargs,
) -> PolicyCandidate:
    now = datetime.now(timezone.utc).isoformat()
    return PolicyCandidate(
        id=kwargs.pop("id", str(uuid.uuid4())),
        tenant_id=kwargs.pop("tenant_id", "tenant-x"),
        type="bypass",
        status=status,
        title="Test",
        business_summary="Testing",
        created_at=now,
        updated_at=now,
        trigger_conditions=conditions or [],
        shadow_run_id=shadow_run_id,
        **kwargs,
    )


def _shadow_run(
    candidate_id: str,
    status: ShadowRunStatus = ShadowRunStatus.RUNNING,
    run_id: str | None = None,
) -> ShadowRun:
    return ShadowRun(
        id=run_id or str(uuid.uuid4()),
        candidate_id=candidate_id,
        tenant_id="tenant-x",
        status=status,
        started_at=datetime.now(timezone.utc).isoformat(),
    )


# ── _extract_context_value ────────────────────────────────────────────────────


class TestExtractContextValue:
    def test_direct_metadata_lookup(self):
        ctx = _ctx(metadata={"intent": "greeting"})
        assert _extract_context_value("intent", ctx) == "greeting"

    def test_intent_from_estixe_result(self):
        ctx = _ctx()
        ctx.estixe_result = MagicMock(intent_category="billing_inquiry")
        assert _extract_context_value("intent", ctx) == "billing_inquiry"

    def test_intent_fallback_when_estixe_none(self):
        ctx = _ctx(metadata={"intent": "greet"})
        ctx.estixe_result = None
        assert _extract_context_value("intent", ctx) == "greet"

    def test_intent_none_when_missing_everywhere(self):
        ctx = _ctx()
        ctx.estixe_result = None
        assert _extract_context_value("intent", ctx) is None

    def test_risk_tier_from_nomos_result(self):
        ctx = _ctx()
        ctx.nomos_result = MagicMock(risk_tier="high")
        assert _extract_context_value("risk_tier", ctx) == "high"

    def test_risk_tier_fallback_when_nomos_none(self):
        ctx = _ctx(metadata={"risk_tier": "low"})
        ctx.nomos_result = None
        assert _extract_context_value("risk_tier", ctx) == "low"

    def test_risk_tier_none_when_missing(self):
        ctx = _ctx()
        ctx.nomos_result = None
        assert _extract_context_value("risk_tier", ctx) is None

    def test_decision_extracted(self):
        ctx = _ctx()
        ctx.decision = Decision.BLOCK
        assert _extract_context_value("decision", ctx) == "block"

    def test_decision_bypass(self):
        ctx = _ctx()
        ctx.decision = Decision.BYPASS
        assert _extract_context_value("decision", ctx) == "bypass"

    def test_decision_none_when_no_decision(self):
        ctx = _ctx()
        ctx.decision = None  # type: ignore[assignment]
        assert _extract_context_value("decision", ctx) is None

    def test_tenant_extracted(self):
        ctx = _ctx(tenant="t-abc")
        assert _extract_context_value("tenant", ctx) == "t-abc"

    def test_pii_detected_true(self):
        ctx = _ctx(metadata={"pii_detected": True})
        assert _extract_context_value("pii_detected", ctx) is True

    def test_pii_detected_false_when_missing(self):
        ctx = _ctx()
        assert _extract_context_value("pii_detected", ctx) is False

    def test_pii_detected_coerced_to_bool(self):
        ctx = _ctx(metadata={"pii_detected": 1})
        assert _extract_context_value("pii_detected", ctx) is True

    def test_unknown_field_returns_none(self):
        ctx = _ctx()
        assert _extract_context_value("nonexistent_field", ctx) is None

    def test_arbitrary_metadata_field_returned(self):
        ctx = _ctx(metadata={"confidence": 0.97})
        assert _extract_context_value("confidence", ctx) == 0.97

    def test_metadata_takes_priority_over_well_known_resolution(self):
        # intent in metadata overrides estixe_result lookup because metadata is checked first
        ctx = _ctx(metadata={"intent": "from_metadata"})
        ctx.estixe_result = MagicMock(intent_category="from_estixe")
        assert _extract_context_value("intent", ctx) == "from_metadata"


# ── _evaluate_condition ───────────────────────────────────────────────────────


class TestEvaluateCondition:
    def _ctx_with(self, field: str, value) -> PipelineContext:
        return _ctx(metadata={field: value})

    def test_equals_match(self):
        ctx = self._ctx_with("intent", "greeting")
        cond = _condition("intent", "equals", "greeting")
        assert _evaluate_condition(cond, ctx) is True

    def test_equals_case_insensitive(self):
        ctx = self._ctx_with("intent", "GREETING")
        cond = _condition("intent", "equals", "greeting")
        assert _evaluate_condition(cond, ctx) is True

    def test_equals_no_match(self):
        ctx = self._ctx_with("intent", "billing")
        cond = _condition("intent", "equals", "greeting")
        assert _evaluate_condition(cond, ctx) is False

    def test_not_equals_match(self):
        ctx = self._ctx_with("intent", "billing")
        cond = _condition("intent", "not_equals", "greeting")
        assert _evaluate_condition(cond, ctx) is True

    def test_not_equals_no_match(self):
        ctx = self._ctx_with("intent", "greeting")
        cond = _condition("intent", "not_equals", "greeting")
        assert _evaluate_condition(cond, ctx) is False

    def test_contains_match(self):
        ctx = self._ctx_with("intent", "segunda via boleto")
        cond = _condition("intent", "contains", "boleto")
        assert _evaluate_condition(cond, ctx) is True

    def test_contains_case_insensitive(self):
        ctx = self._ctx_with("intent", "SEGUNDA VIA BOLETO")
        cond = _condition("intent", "contains", "boleto")
        assert _evaluate_condition(cond, ctx) is True

    def test_contains_no_match(self):
        ctx = self._ctx_with("intent", "greeting")
        cond = _condition("intent", "contains", "boleto")
        assert _evaluate_condition(cond, ctx) is False

    def test_in_with_list(self):
        ctx = self._ctx_with("intent", "greeting")
        cond = _condition("intent", "in", ["greeting", "farewell"])
        assert _evaluate_condition(cond, ctx) is True

    def test_in_with_single_value(self):
        ctx = self._ctx_with("intent", "greeting")
        cond = _condition("intent", "in", "greeting")
        assert _evaluate_condition(cond, ctx) is True

    def test_in_no_match(self):
        ctx = self._ctx_with("intent", "billing")
        cond = _condition("intent", "in", ["greeting", "farewell"])
        assert _evaluate_condition(cond, ctx) is False

    def test_matches_pattern_match(self):
        ctx = self._ctx_with("intent", "oi tudo bem")
        cond = _condition("intent", "matches_pattern", r"^(oi|olá|bom dia)")
        assert _evaluate_condition(cond, ctx) is True

    def test_matches_pattern_case_insensitive(self):
        ctx = self._ctx_with("intent", "OI")
        cond = _condition("intent", "matches_pattern", r"^oi$")
        assert _evaluate_condition(cond, ctx) is True

    def test_matches_pattern_no_match(self):
        ctx = self._ctx_with("intent", "billing inquiry")
        cond = _condition("intent", "matches_pattern", r"^(oi|olá)")
        assert _evaluate_condition(cond, ctx) is False

    def test_gte_match(self):
        ctx = self._ctx_with("confidence", 0.95)
        cond = _condition("confidence", "gte", 0.90)
        assert _evaluate_condition(cond, ctx) is True

    def test_gte_equal_counts(self):
        ctx = self._ctx_with("confidence", 0.90)
        cond = _condition("confidence", "gte", 0.90)
        assert _evaluate_condition(cond, ctx) is True

    def test_gte_no_match(self):
        ctx = self._ctx_with("confidence", 0.80)
        cond = _condition("confidence", "gte", 0.90)
        assert _evaluate_condition(cond, ctx) is False

    def test_lte_match(self):
        ctx = self._ctx_with("confidence", 0.50)
        cond = _condition("confidence", "lte", 0.70)
        assert _evaluate_condition(cond, ctx) is True

    def test_lte_no_match(self):
        ctx = self._ctx_with("confidence", 0.90)
        cond = _condition("confidence", "lte", 0.70)
        assert _evaluate_condition(cond, ctx) is False

    def test_actual_none_returns_false(self):
        ctx = _ctx()  # no metadata, intent will be None
        cond = _condition("intent", "equals", "greeting")
        assert _evaluate_condition(cond, ctx) is False

    def test_bad_pattern_returns_false(self):
        ctx = self._ctx_with("intent", "greeting")
        cond = _condition("intent", "matches_pattern", "[invalid(")
        assert _evaluate_condition(cond, ctx) is False

    def test_gte_non_numeric_returns_false(self):
        ctx = self._ctx_with("confidence", "not_a_number")
        cond = _condition("confidence", "gte", 0.90)
        assert _evaluate_condition(cond, ctx) is False


# ── _candidate_matches ────────────────────────────────────────────────────────


class TestCandidateMatches:
    def test_empty_conditions_always_match(self):
        ctx = _ctx()
        candidate = _candidate(conditions=[])
        assert _candidate_matches(candidate, ctx) is True

    def test_all_conditions_match(self):
        ctx = _ctx(metadata={"intent": "billing", "risk_tier": "low"})
        conditions = [
            _condition("intent", "equals", "billing"),
            _condition("risk_tier", "equals", "low"),
        ]
        candidate = _candidate(conditions=conditions)
        assert _candidate_matches(candidate, ctx) is True

    def test_one_condition_fails(self):
        ctx = _ctx(metadata={"intent": "billing", "risk_tier": "high"})
        conditions = [
            _condition("intent", "equals", "billing"),
            _condition("risk_tier", "equals", "low"),  # fails
        ]
        candidate = _candidate(conditions=conditions)
        assert _candidate_matches(candidate, ctx) is False

    def test_first_condition_fails_short_circuits(self):
        ctx = _ctx()  # no metadata → intent is None → equals fails
        conditions = [
            _condition("intent", "equals", "billing"),
            _condition("risk_tier", "equals", "low"),
        ]
        candidate = _candidate(conditions=conditions)
        assert _candidate_matches(candidate, ctx) is False


# ── KairosShadowEvaluator.evaluate() ─────────────────────────────────────────


class TestEvaluatorEvaluate:
    @pytest.fixture
    def evaluator(self):
        return KairosShadowEvaluator()

    async def test_kairos_disabled_returns_silently(self, evaluator):
        ctx = _ctx()
        with patch("aion.kairos.get_kairos", side_effect=RuntimeError("disabled")):
            await evaluator.evaluate(ctx)  # must not raise

    async def test_no_tenant_returns_silently(self, evaluator):
        ctx = _ctx(tenant="")
        mock_kairos = MagicMock()
        with patch("aion.kairos.get_kairos", return_value=mock_kairos):
            await evaluator.evaluate(ctx)
        mock_kairos.store.list_shadow_running_candidates.assert_not_called()

    async def test_list_candidates_fails_returns_silently(self, evaluator):
        ctx = _ctx(tenant="t1")
        mock_store = AsyncMock()
        mock_store.list_shadow_running_candidates.side_effect = Exception("db down")
        mock_kairos = MagicMock(store=mock_store)
        with patch("aion.kairos.get_kairos", return_value=mock_kairos):
            await evaluator.evaluate(ctx)  # must not raise

    async def test_no_candidates_returns_silently(self, evaluator):
        ctx = _ctx(tenant="t1")
        mock_store = AsyncMock()
        mock_store.list_shadow_running_candidates.return_value = []
        mock_kairos = MagicMock(store=mock_store)
        with patch("aion.kairos.get_kairos", return_value=mock_kairos):
            await evaluator.evaluate(ctx)
        mock_store.increment_shadow_counters.assert_not_called()

    async def test_matched_candidate_increments_counters(self, evaluator):
        run_id = str(uuid.uuid4())
        candidate = _candidate(
            conditions=[],  # empty → always matches
            shadow_run_id=run_id,
        )
        run = _shadow_run(candidate.id, run_id=run_id)

        mock_store = AsyncMock()
        mock_store.list_shadow_running_candidates.return_value = [candidate]
        mock_store.get_shadow_run.return_value = run
        mock_kairos = MagicMock(store=mock_store)

        ctx = _ctx(tenant="tenant-x")
        with patch("aion.kairos.get_kairos", return_value=mock_kairos):
            await evaluator.evaluate(ctx)

        mock_store.increment_shadow_counters.assert_called_once_with(
            run.id, matched=1, fallback=0, observations=1
        )

    async def test_unmatched_candidate_increments_observation_only(self, evaluator):
        run_id = str(uuid.uuid4())
        conditions = [_condition("intent", "equals", "greeting")]
        candidate = _candidate(conditions=conditions, shadow_run_id=run_id)
        run = _shadow_run(candidate.id, run_id=run_id)

        mock_store = AsyncMock()
        mock_store.list_shadow_running_candidates.return_value = [candidate]
        mock_store.get_shadow_run.return_value = run

        # Context has no intent → condition fails → matched=0
        ctx = _ctx(tenant="tenant-x")
        mock_kairos = MagicMock(store=mock_store)
        with patch("aion.kairos.get_kairos", return_value=mock_kairos):
            await evaluator.evaluate(ctx)

        mock_store.increment_shadow_counters.assert_called_once_with(
            run.id, matched=0, fallback=0, observations=1
        )

    async def test_get_kairos_unexpected_exception_returns_silently(self, evaluator):
        ctx = _ctx()
        with patch("aion.kairos.get_kairos", side_effect=ImportError("partial import")):
            await evaluator.evaluate(ctx)  # must not raise

    async def test_candidate_with_mismatched_tenant_id_is_skipped(self, evaluator):
        run_id = str(uuid.uuid4())
        # Store returns a candidate belonging to a different tenant (simulates store bug)
        other_tenant_candidate = _candidate(
            shadow_run_id=run_id, tenant_id="OTHER-tenant", conditions=[]
        )
        mock_store = AsyncMock()
        mock_store.list_shadow_running_candidates.return_value = [other_tenant_candidate]
        mock_kairos = MagicMock(store=mock_store)
        ctx = _ctx(tenant="tenant-x")
        with patch("aion.kairos.get_kairos", return_value=mock_kairos):
            await evaluator.evaluate(ctx)
        mock_store.increment_shadow_counters.assert_not_called()

    async def test_error_in_one_candidate_does_not_stop_others(self, evaluator):
        run_id_a = str(uuid.uuid4())
        run_id_b = str(uuid.uuid4())
        cand_a = _candidate(shadow_run_id=run_id_a, id=str(uuid.uuid4()))
        cand_b = _candidate(shadow_run_id=run_id_b, id=str(uuid.uuid4()))
        run_b = _shadow_run(cand_b.id, run_id=run_id_b)

        mock_store = AsyncMock()
        mock_store.list_shadow_running_candidates.return_value = [cand_a, cand_b]

        call_count = 0

        async def _get_shadow_run(rid):
            nonlocal call_count
            call_count += 1
            if rid == run_id_a:
                raise Exception("store error for cand_a")
            return run_b

        mock_store.get_shadow_run.side_effect = _get_shadow_run
        mock_kairos = MagicMock(store=mock_store)

        ctx = _ctx(tenant="tenant-x")
        with patch("aion.kairos.get_kairos", return_value=mock_kairos):
            await evaluator.evaluate(ctx)

        # cand_b was still observed despite cand_a failure
        mock_store.increment_shadow_counters.assert_called_once_with(
            run_b.id, matched=1, fallback=0, observations=1
        )


# ── KairosShadowEvaluator._observe() ─────────────────────────────────────────


class TestEvaluatorObserve:
    @pytest.fixture
    def evaluator(self):
        return KairosShadowEvaluator()

    @pytest.fixture
    def mock_kairos(self):
        mock_store = AsyncMock()
        kairos = MagicMock(store=mock_store)
        return kairos

    async def test_no_shadow_run_id_returns_early(self, evaluator, mock_kairos):
        candidate = _candidate(shadow_run_id=None)
        ctx = _ctx()
        await evaluator._observe(candidate, ctx, mock_kairos)
        mock_kairos.store.get_shadow_run.assert_not_called()
        mock_kairos.store.increment_shadow_counters.assert_not_called()

    async def test_run_not_found_returns_early(self, evaluator, mock_kairos):
        candidate = _candidate(shadow_run_id="run-missing")
        mock_kairos.store.get_shadow_run.return_value = None
        ctx = _ctx()
        await evaluator._observe(candidate, ctx, mock_kairos)
        mock_kairos.store.increment_shadow_counters.assert_not_called()

    async def test_run_not_running_returns_early(self, evaluator, mock_kairos):
        run_id = str(uuid.uuid4())
        candidate = _candidate(shadow_run_id=run_id)
        run = _shadow_run(candidate.id, status=ShadowRunStatus.COMPLETED, run_id=run_id)
        mock_kairos.store.get_shadow_run.return_value = run
        ctx = _ctx()
        await evaluator._observe(candidate, ctx, mock_kairos)
        mock_kairos.store.increment_shadow_counters.assert_not_called()

    async def test_matched_increments_matched_one(self, evaluator, mock_kairos):
        run_id = str(uuid.uuid4())
        candidate = _candidate(conditions=[], shadow_run_id=run_id)  # always matches
        run = _shadow_run(candidate.id, run_id=run_id)
        mock_kairos.store.get_shadow_run.return_value = run
        ctx = _ctx()
        await evaluator._observe(candidate, ctx, mock_kairos)
        mock_kairos.store.increment_shadow_counters.assert_called_once_with(
            run.id, matched=1, fallback=0, observations=1
        )

    async def test_unmatched_increments_matched_zero(self, evaluator, mock_kairos):
        run_id = str(uuid.uuid4())
        conditions = [_condition("intent", "equals", "billing")]
        candidate = _candidate(conditions=conditions, shadow_run_id=run_id)
        run = _shadow_run(candidate.id, run_id=run_id)
        mock_kairos.store.get_shadow_run.return_value = run
        ctx = _ctx()  # no intent → not matched
        await evaluator._observe(candidate, ctx, mock_kairos)
        mock_kairos.store.increment_shadow_counters.assert_called_once_with(
            run.id, matched=0, fallback=0, observations=1
        )

    async def test_run_failed_status_returns_early(self, evaluator, mock_kairos):
        run_id = str(uuid.uuid4())
        candidate = _candidate(shadow_run_id=run_id)
        run = _shadow_run(candidate.id, status=ShadowRunStatus.FAILED, run_id=run_id)
        mock_kairos.store.get_shadow_run.return_value = run
        ctx = _ctx()
        await evaluator._observe(candidate, ctx, mock_kairos)
        mock_kairos.store.increment_shadow_counters.assert_not_called()
