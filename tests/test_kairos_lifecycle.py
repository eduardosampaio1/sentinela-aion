"""Unit tests for aion/kairos/lifecycle.py — Fase 2: State Machine.

Tests cover:
- State machine helper functions (can_transition, allowed_transitions)
- KairosLifecycleManager.transition() — valid and invalid transitions
- start_shadow(), complete_shadow() — ShadowRun creation and summary calculation
- approve(), reject()
- sweep() / _check_and_complete() — completion by obs count and duration
- Edge cases: missing shadow_run_id, already-completed run, timezone handling
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from aion.kairos.lifecycle import (
    KairosLifecycleManager,
    allowed_transitions,
    can_transition,
)
from aion.kairos.models import (
    LifecycleActorType,
    PolicyCandidate,
    PolicyCandidateStatus,
    ShadowRun,
    ShadowRunStatus,
)
from aion.kairos.settings import KairosSettings


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _settings(**overrides) -> KairosSettings:
    base = {
        "storage_mode": "sqlite",
        "shadow_min_observations": 100,
        "shadow_duration_hours": 24,
    }
    base.update(overrides)
    return KairosSettings(**base)


def _candidate(status: PolicyCandidateStatus = PolicyCandidateStatus.DRAFT, **kwargs) -> PolicyCandidate:
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant-test",
        "type": "bypass",
        "status": status,
        "title": "Test policy",
        "business_summary": "For testing",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    return PolicyCandidate(**defaults)


def _shadow_run(candidate_id: str, status: ShadowRunStatus = ShadowRunStatus.RUNNING, **kwargs) -> ShadowRun:
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": str(uuid.uuid4()),
        "candidate_id": candidate_id,
        "tenant_id": "tenant-test",
        "status": status,
        "started_at": now,
        "observations_count": 0,
        "matched_count": 0,
        "fallback_count": 0,
    }
    defaults.update(kwargs)
    return ShadowRun(**defaults)


def _mock_store() -> MagicMock:
    store = MagicMock()
    store.save_candidate = AsyncMock()
    store.save_lifecycle_event = AsyncMock()
    store.save_shadow_run = AsyncMock()
    store.get_shadow_run = AsyncMock(return_value=None)
    store.list_shadow_running_candidates = AsyncMock(return_value=[])
    return store


def _manager(store=None, **settings_overrides) -> KairosLifecycleManager:
    if store is None:
        store = _mock_store()
    return KairosLifecycleManager(store, _settings(**settings_overrides))


# ── State machine helpers ──────────────────────────────────────────────────────


class TestCanTransition:
    def test_draft_to_ready_for_shadow(self):
        assert can_transition("draft", "ready_for_shadow") is True

    def test_draft_to_under_review(self):
        assert can_transition("draft", "under_review") is True

    def test_draft_cannot_skip_to_shadow_running(self):
        assert can_transition("draft", "shadow_running") is False

    def test_draft_cannot_jump_to_approved(self):
        assert can_transition("draft", "approved_production") is False

    def test_ready_for_shadow_to_shadow_running(self):
        assert can_transition("ready_for_shadow", "shadow_running") is True

    def test_shadow_running_to_shadow_completed(self):
        assert can_transition("shadow_running", "shadow_completed") is True

    def test_shadow_completed_to_approved(self):
        assert can_transition("shadow_completed", "approved_production") is True

    def test_shadow_completed_to_rejected(self):
        assert can_transition("shadow_completed", "rejected") is True

    def test_shadow_completed_to_under_review(self):
        assert can_transition("shadow_completed", "under_review") is True

    def test_approved_to_deprecated(self):
        assert can_transition("approved_production", "deprecated") is True

    def test_approved_to_under_review(self):
        assert can_transition("approved_production", "under_review") is True

    def test_under_review_to_rejected(self):
        assert can_transition("under_review", "rejected") is True

    def test_under_review_to_ready_for_shadow(self):
        assert can_transition("under_review", "ready_for_shadow") is True

    def test_deprecated_to_archived(self):
        assert can_transition("deprecated", "archived") is True

    def test_rejected_to_archived(self):
        assert can_transition("rejected", "archived") is True

    def test_archived_is_terminal(self):
        assert can_transition("archived", "draft") is False
        assert can_transition("archived", "rejected") is False
        assert can_transition("archived", "archived") is False

    def test_unknown_status_returns_false(self):
        assert can_transition("nonexistent", "draft") is False

    def test_cannot_go_backwards_shadow_completed_to_running(self):
        assert can_transition("shadow_completed", "shadow_running") is False

    def test_approved_cannot_go_back_to_shadow(self):
        assert can_transition("approved_production", "shadow_running") is False


class TestAllowedTransitions:
    def test_archived_empty(self):
        assert allowed_transitions("archived") == frozenset()

    def test_draft_has_two_options(self):
        result = allowed_transitions("draft")
        assert "ready_for_shadow" in result
        assert "under_review" in result
        assert len(result) == 2

    def test_unknown_status_empty(self):
        assert allowed_transitions("does_not_exist") == frozenset()


# ── KairosLifecycleManager.transition() ───────────────────────────────────────


class TestTransition:
    @pytest.mark.asyncio
    async def test_valid_transition_updates_status(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        result = await mgr.transition(
            c,
            PolicyCandidateStatus.READY_FOR_SHADOW,
            actor_type=LifecycleActorType.OPERATOR,
            actor_id="op-1",
            reason="approved by operator",
        )

        assert result.status == PolicyCandidateStatus.READY_FOR_SHADOW

    @pytest.mark.asyncio
    async def test_valid_transition_saves_candidate(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        await mgr.transition(c, PolicyCandidateStatus.READY_FOR_SHADOW, LifecycleActorType.OPERATOR)

        store.save_candidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_valid_transition_saves_lifecycle_event(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        await mgr.transition(c, PolicyCandidateStatus.READY_FOR_SHADOW, LifecycleActorType.OPERATOR)

        store.save_lifecycle_event.assert_awaited_once()
        event = store.save_lifecycle_event.call_args[0][0]
        assert event.from_status == "draft"
        assert event.to_status == "ready_for_shadow"
        assert event.candidate_id == c.id

    @pytest.mark.asyncio
    async def test_invalid_transition_raises_value_error(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        with pytest.raises(ValueError, match="not allowed"):
            await mgr.transition(c, PolicyCandidateStatus.APPROVED_PRODUCTION, LifecycleActorType.OPERATOR)

    @pytest.mark.asyncio
    async def test_invalid_transition_does_not_save(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.ARCHIVED)

        with pytest.raises(ValueError):
            await mgr.transition(c, PolicyCandidateStatus.DRAFT, LifecycleActorType.OPERATOR)

        store.save_candidate.assert_not_awaited()
        store.save_lifecycle_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_metadata_passed_to_event(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)
        meta = {"source": "unit_test"}

        await mgr.transition(c, PolicyCandidateStatus.UNDER_REVIEW, LifecycleActorType.SYSTEM, metadata=meta)

        event = store.save_lifecycle_event.call_args[0][0]
        assert event.metadata == meta

    @pytest.mark.asyncio
    async def test_updated_at_changes(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)
        original_updated_at = datetime.fromisoformat(c.updated_at)

        import asyncio
        await asyncio.sleep(0.01)
        result = await mgr.transition(c, PolicyCandidateStatus.READY_FOR_SHADOW, LifecycleActorType.OPERATOR)

        result_updated_at = datetime.fromisoformat(result.updated_at.replace("Z", "+00:00"))
        assert result_updated_at >= original_updated_at

    @pytest.mark.asyncio
    async def test_metadata_none_becomes_empty_dict(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        await mgr.transition(c, PolicyCandidateStatus.READY_FOR_SHADOW, LifecycleActorType.OPERATOR, metadata=None)

        event = store.save_lifecycle_event.call_args[0][0]
        assert event.metadata == {}

    @pytest.mark.asyncio
    async def test_error_message_includes_allowed_set(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        with pytest.raises(ValueError) as exc_info:
            await mgr.transition(c, PolicyCandidateStatus.SHADOW_RUNNING, LifecycleActorType.OPERATOR)

        assert "ready_for_shadow" in str(exc_info.value)
        assert "under_review" in str(exc_info.value)


# ── start_shadow() ────────────────────────────────────────────────────────────


class TestStartShadow:
    @pytest.mark.asyncio
    async def test_creates_shadow_run(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.READY_FOR_SHADOW)

        candidate, run = await mgr.start_shadow(c)

        assert run.status == ShadowRunStatus.RUNNING
        assert run.candidate_id == c.id
        store.save_shadow_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transitions_to_shadow_running(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.READY_FOR_SHADOW)

        candidate, run = await mgr.start_shadow(c)

        assert candidate.status == PolicyCandidateStatus.SHADOW_RUNNING

    @pytest.mark.asyncio
    async def test_links_shadow_run_id(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.READY_FOR_SHADOW)

        candidate, run = await mgr.start_shadow(c)

        assert candidate.shadow_run_id == run.id

    @pytest.mark.asyncio
    async def test_fails_from_wrong_status(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        with pytest.raises(ValueError, match="not allowed"):
            await mgr.start_shadow(c)

    @pytest.mark.asyncio
    async def test_no_orphan_shadow_run_on_invalid_status(self):
        """ShadowRun must NOT be persisted when transition would fail."""
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        with pytest.raises(ValueError):
            await mgr.start_shadow(c)

        store.save_shadow_run.assert_not_awaited()


# ── complete_shadow() ─────────────────────────────────────────────────────────


class TestCompleteShadow:
    @pytest.mark.asyncio
    async def test_transitions_to_shadow_completed(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, observations_count=200, matched_count=150, fallback_count=10)

        candidate, completed_run = await mgr.complete_shadow(c, run)

        assert candidate.status == PolicyCandidateStatus.SHADOW_COMPLETED

    @pytest.mark.asyncio
    async def test_run_marked_completed(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, observations_count=200, matched_count=150, fallback_count=10)

        candidate, completed_run = await mgr.complete_shadow(c, run)

        assert completed_run.status == ShadowRunStatus.COMPLETED
        assert completed_run.completed_at is not None

    @pytest.mark.asyncio
    async def test_summary_calculation(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, observations_count=200, matched_count=150, fallback_count=20)

        candidate, completed_run = await mgr.complete_shadow(c, run)

        summary = completed_run.summary
        assert summary is not None
        assert summary["observations"] == 200
        assert summary["matched"] == 150
        assert summary["fallback"] == 20
        assert summary["match_rate"] == round(150 / 200, 4)
        assert summary["fallback_rate"] == round(20 / 200, 4)

    @pytest.mark.asyncio
    async def test_summary_zero_observations(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, observations_count=0, matched_count=0, fallback_count=0)

        candidate, completed_run = await mgr.complete_shadow(c, run)

        summary = completed_run.summary
        assert summary["match_rate"] == 0.0
        assert summary["fallback_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_rejects_already_completed_run(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, status=ShadowRunStatus.COMPLETED, observations_count=500)

        with pytest.raises(ValueError, match="already"):
            await mgr.complete_shadow(c, run)

    @pytest.mark.asyncio
    async def test_rejects_mismatched_candidate_and_run(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run("different-candidate-id")  # mismatch

        with pytest.raises(ValueError, match="belongs to"):
            await mgr.complete_shadow(c, run)

    @pytest.mark.asyncio
    async def test_summary_in_lifecycle_event_metadata(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, observations_count=50, matched_count=40, fallback_count=5)

        await mgr.complete_shadow(c, run, reason="min_observations_reached")

        events = [call[0][0] for call in store.save_lifecycle_event.call_args_list]
        event = events[-1]
        assert "summary" in event.metadata
        assert event.reason == "min_observations_reached"


# ── approve() ────────────────────────────────────────────────────────────────


class TestApprove:
    @pytest.mark.asyncio
    async def test_transitions_to_approved_production(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_COMPLETED)

        result = await mgr.approve(c, actor_id="admin-1")

        assert result.status == PolicyCandidateStatus.APPROVED_PRODUCTION

    @pytest.mark.asyncio
    async def test_sets_approved_by(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_COMPLETED)

        result = await mgr.approve(c, actor_id="admin-1")

        assert result.approved_by == "admin-1"
        assert result.approved_at is not None

    @pytest.mark.asyncio
    async def test_cannot_approve_from_draft(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        with pytest.raises(ValueError):
            await mgr.approve(c, actor_id="admin-1")


# ── reject() ─────────────────────────────────────────────────────────────────


class TestReject:
    @pytest.mark.asyncio
    async def test_transitions_to_rejected(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_COMPLETED)

        result = await mgr.reject(c, actor_id="admin-1", reason="too many false positives")

        assert result.status == PolicyCandidateStatus.REJECTED

    @pytest.mark.asyncio
    async def test_sets_rejection_reason(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.SHADOW_COMPLETED)

        result = await mgr.reject(c, actor_id="admin-1", reason="too many false positives")

        assert result.rejection_reason == "too many false positives"

    @pytest.mark.asyncio
    async def test_can_reject_from_under_review(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.UNDER_REVIEW)

        result = await mgr.reject(c, actor_id="admin-1", reason="policy conflict")

        assert result.status == PolicyCandidateStatus.REJECTED

    @pytest.mark.asyncio
    async def test_cannot_reject_from_draft(self):
        store = _mock_store()
        mgr = _manager(store)
        c = _candidate(PolicyCandidateStatus.DRAFT)

        with pytest.raises(ValueError):
            await mgr.reject(c, actor_id="admin-1", reason="whatever")


# ── sweep() / _check_and_complete() ──────────────────────────────────────────


class TestSweep:
    @pytest.mark.asyncio
    async def test_sweep_returns_zero_when_no_candidates(self):
        store = _mock_store()
        store.list_shadow_running_candidates = AsyncMock(return_value=[])
        mgr = _manager(store)

        count = await mgr.sweep()

        assert count == 0

    @pytest.mark.asyncio
    async def test_sweep_completes_candidate_by_obs_count(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, observations_count=150)  # >= 100 (min_observations)
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=100, shadow_duration_hours=9999)

        count = await mgr.sweep()

        assert count == 1

    @pytest.mark.asyncio
    async def test_sweep_completes_candidate_by_duration(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        old_started = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        run = _shadow_run(c.id, observations_count=0, started_at=old_started)  # < 100 obs but expired
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=100, shadow_duration_hours=24)

        count = await mgr.sweep()

        assert count == 1

    @pytest.mark.asyncio
    async def test_sweep_skips_candidate_not_meeting_criteria(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        recent_started = datetime.now(timezone.utc).isoformat()
        run = _shadow_run(c.id, observations_count=10, started_at=recent_started)
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=100, shadow_duration_hours=24)

        count = await mgr.sweep()

        assert count == 0

    @pytest.mark.asyncio
    async def test_sweep_skips_candidate_without_shadow_run_id(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        # shadow_run_id is None by default

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        mgr = _manager(store)

        count = await mgr.sweep()

        assert count == 0
        store.get_shadow_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sweep_skips_already_completed_run(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, status=ShadowRunStatus.COMPLETED, observations_count=500)
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=100)

        count = await mgr.sweep()

        assert count == 0

    @pytest.mark.asyncio
    async def test_sweep_skips_missing_run(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        c = c.model_copy(update={"shadow_run_id": "nonexistent-run-id"})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=None)
        mgr = _manager(store)

        count = await mgr.sweep()

        assert count == 0

    @pytest.mark.asyncio
    async def test_sweep_continues_after_single_candidate_error(self):
        store = _mock_store()
        c1 = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        c2 = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)

        good_run = _shadow_run(c2.id, observations_count=500)
        c2 = c2.model_copy(update={"shadow_run_id": good_run.id})

        # c1 has no shadow_run_id — will return 0 (skip)
        # c2 has sufficient observations — will complete

        store.list_shadow_running_candidates = AsyncMock(return_value=[c1, c2])
        store.get_shadow_run = AsyncMock(return_value=good_run)
        mgr = _manager(store, shadow_min_observations=100, shadow_duration_hours=9999)

        count = await mgr.sweep()

        assert count == 1

    @pytest.mark.asyncio
    async def test_sweep_reason_obs_count(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id, observations_count=200)
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=100, shadow_duration_hours=9999)

        await mgr.sweep()

        # Check lifecycle event carries the right reason
        events = [call[0][0] for call in store.save_lifecycle_event.call_args_list]
        assert any(e.reason == "min_observations_reached" for e in events)

    @pytest.mark.asyncio
    async def test_sweep_reason_duration_expired(self):
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        old_started = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        run = _shadow_run(c.id, observations_count=0, started_at=old_started)
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=9999, shadow_duration_hours=24)

        await mgr.sweep()

        events = [call[0][0] for call in store.save_lifecycle_event.call_args_list]
        assert any(e.reason == "duration_expired" for e in events)

    @pytest.mark.asyncio
    async def test_sweep_handles_naive_datetime_in_started_at(self):
        """started_at stored without tzinfo (legacy or SQLite behaviour) should not crash."""
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        # Naive ISO string — no timezone suffix
        naive_started = (datetime.now(timezone.utc) - timedelta(hours=48)).replace(tzinfo=None).isoformat()
        run = _shadow_run(c.id, observations_count=0, started_at=naive_started)
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=9999, shadow_duration_hours=24)

        count = await mgr.sweep()

        assert count == 1  # duration expired, naive datetime handled correctly

    @pytest.mark.asyncio
    async def test_sweep_handles_z_suffix_started_at(self):
        """started_at with 'Z' suffix must not crash on Python 3.10."""
        store = _mock_store()
        c = _candidate(PolicyCandidateStatus.SHADOW_RUNNING)
        z_started = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        run = _shadow_run(c.id, observations_count=0, started_at=z_started)
        c = c.model_copy(update={"shadow_run_id": run.id})

        store.list_shadow_running_candidates = AsyncMock(return_value=[c])
        store.get_shadow_run = AsyncMock(return_value=run)
        mgr = _manager(store, shadow_min_observations=9999, shadow_duration_hours=24)

        count = await mgr.sweep()

        assert count == 1


# ── KairosModule integration ──────────────────────────────────────────────────


class TestKairosModuleLifecycleManager:
    def test_lifecycle_manager_property_accessible(self):
        from aion.kairos import KairosModule
        from aion.kairos.settings import KairosSettings

        settings = KairosSettings(storage_mode="sqlite")
        module = KairosModule(settings)

        mgr = module.lifecycle_manager
        assert isinstance(mgr, KairosLifecycleManager)

    def test_lifecycle_manager_property_cached(self):
        from aion.kairos import KairosModule
        from aion.kairos.settings import KairosSettings

        settings = KairosSettings(storage_mode="sqlite")
        module = KairosModule(settings)

        mgr1 = module.lifecycle_manager
        mgr2 = module.lifecycle_manager

        assert mgr1 is mgr2

    def test_lifecycle_manager_uses_module_store(self):
        from aion.kairos import KairosModule
        from aion.kairos.settings import KairosSettings

        settings = KairosSettings(storage_mode="sqlite")
        module = KairosModule(settings)

        mgr = module.lifecycle_manager
        assert mgr._store is module.store
