"""KAIROS lifecycle manager — state machine + sweep loop.

State machine:
  draft → ready_for_shadow → shadow_running → shadow_completed
    → approved_production → deprecated → archived
    → rejected → archived
  any (except archived) → under_review
  under_review → rejected | ready_for_shadow
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from aion.kairos.models import (
    LifecycleActorType,
    LifecycleEvent,
    PolicyCandidate,
    PolicyCandidateStatus,
    ShadowRun,
    ShadowRunStatus,
)
from aion.kairos.settings import KairosSettings
from aion.kairos.store.base import KairosStore

logger = logging.getLogger("aion.kairos.lifecycle")

# Strong references to fire-and-forget telemetry tasks — prevents GC before completion.
_BG_TASKS: set[asyncio.Task] = set()


def _fire_telemetry(coro) -> None:
    """Schedule a telemetry coroutine as a fire-and-forget background task."""
    try:
        t = asyncio.create_task(coro)
        _BG_TASKS.add(t)
        t.add_done_callback(_BG_TASKS.discard)
    except Exception:
        logger.debug("KAIROS telemetry: task creation failed (non-critical)", exc_info=True)

# ── State machine ──────────────────────────────────────────────────────────────

# Design invariant: DEPRECATED is only reachable from APPROVED_PRODUCTION.
# A policy must be approved before it can be deprecated — there is no shortcut
# from SHADOW_COMPLETED → DEPRECATED. The operator must explicitly approve first.
_TRANSITIONS: dict[str, frozenset[str]] = {
    PolicyCandidateStatus.DRAFT.value: frozenset({
        PolicyCandidateStatus.READY_FOR_SHADOW.value,
        PolicyCandidateStatus.UNDER_REVIEW.value,
    }),
    PolicyCandidateStatus.READY_FOR_SHADOW.value: frozenset({
        PolicyCandidateStatus.SHADOW_RUNNING.value,
        PolicyCandidateStatus.UNDER_REVIEW.value,
    }),
    PolicyCandidateStatus.SHADOW_RUNNING.value: frozenset({
        PolicyCandidateStatus.SHADOW_COMPLETED.value,
        PolicyCandidateStatus.UNDER_REVIEW.value,
    }),
    PolicyCandidateStatus.SHADOW_COMPLETED.value: frozenset({
        PolicyCandidateStatus.APPROVED_PRODUCTION.value,
        PolicyCandidateStatus.REJECTED.value,
        PolicyCandidateStatus.UNDER_REVIEW.value,
        # Note: DEPRECATED is intentionally absent — must be approved before deprecated.
    }),
    PolicyCandidateStatus.APPROVED_PRODUCTION.value: frozenset({
        PolicyCandidateStatus.DEPRECATED.value,
        PolicyCandidateStatus.UNDER_REVIEW.value,
    }),
    PolicyCandidateStatus.UNDER_REVIEW.value: frozenset({
        PolicyCandidateStatus.REJECTED.value,
        PolicyCandidateStatus.READY_FOR_SHADOW.value,
    }),
    PolicyCandidateStatus.DEPRECATED.value: frozenset({
        PolicyCandidateStatus.ARCHIVED.value,
    }),
    PolicyCandidateStatus.REJECTED.value: frozenset({
        PolicyCandidateStatus.ARCHIVED.value,
    }),
    PolicyCandidateStatus.ARCHIVED.value: frozenset(),
}


def can_transition(from_status: str, to_status: str) -> bool:
    """Return True if the transition is allowed by the state machine."""
    return to_status in _TRANSITIONS.get(from_status, frozenset())


def allowed_transitions(from_status: str) -> frozenset[str]:
    """Return the set of allowed target statuses from a given status."""
    return _TRANSITIONS.get(from_status, frozenset())


async def _emit_telemetry_safe(
    candidate: PolicyCandidate,
    from_status: Optional[str],
    to_status: str,
    actor_type: str,
    shadow_run: Optional[ShadowRun] = None,
) -> None:
    """Safely emit telemetry — all exceptions caught and logged at DEBUG."""
    try:
        from aion.kairos.telemetry import get_telemetry_exporter
        await get_telemetry_exporter().emit_lifecycle_transition(
            candidate=candidate,
            from_status=from_status,
            to_status=to_status,
            actor_type=actor_type,
            shadow_run=shadow_run,
        )
    except Exception:
        logger.debug("KAIROS telemetry: emit failed (non-critical)", exc_info=True)


# ── KairosLifecycleManager ────────────────────────────────────────────────────


class KairosLifecycleManager:
    """Manages state transitions and shadow run lifecycle for PolicyCandidates."""

    def __init__(self, store: KairosStore, settings: KairosSettings) -> None:
        self._store = store
        self._settings = settings

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def transition(
        self,
        candidate: PolicyCandidate,
        to_status: PolicyCandidateStatus,
        actor_type: LifecycleActorType,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> PolicyCandidate:
        """Validate and apply a state transition. Returns the updated candidate.

        Raises ValueError if the transition is not allowed by the state machine.
        """
        from_value = candidate.status.value
        to_value = to_status.value

        if not can_transition(from_value, to_value):
            raise ValueError(
                f"Transition {from_value!r} → {to_value!r} is not allowed. "
                f"Allowed from {from_value!r}: {sorted(allowed_transitions(from_value))}"
            )

        now = self._now_iso()
        candidate = candidate.model_copy(update={"status": to_status, "updated_at": now})

        event = LifecycleEvent(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            tenant_id=candidate.tenant_id,
            from_status=from_value,
            to_status=to_value,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            metadata=metadata or {},
            created_at=now,
        )

        await self._store.save_candidate(candidate)
        await self._store.save_lifecycle_event(event)
        return candidate

    async def start_shadow(
        self,
        candidate: PolicyCandidate,
        actor_id: Optional[str] = None,
    ) -> tuple[PolicyCandidate, ShadowRun]:
        """Create a ShadowRun and transition candidate to shadow_running.

        Raises ValueError if candidate is not in ready_for_shadow.
        """
        # Validate transition BEFORE creating the run to avoid orphan ShadowRuns.
        if not can_transition(candidate.status.value, PolicyCandidateStatus.SHADOW_RUNNING.value):
            raise ValueError(
                f"Transition {candidate.status.value!r} → 'shadow_running' is not allowed. "
                f"Allowed from {candidate.status.value!r}: {sorted(allowed_transitions(candidate.status.value))}"
            )

        now = self._now_iso()
        run = ShadowRun(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            tenant_id=candidate.tenant_id,
            status=ShadowRunStatus.RUNNING,
            started_at=now,
        )
        await self._store.save_shadow_run(run)

        candidate = candidate.model_copy(update={"shadow_run_id": run.id})
        candidate = await self.transition(
            candidate,
            PolicyCandidateStatus.SHADOW_RUNNING,
            actor_type=LifecycleActorType.OPERATOR,
            actor_id=actor_id,
            reason="shadow_run_started",
            metadata={"shadow_run_id": run.id},
        )
        return candidate, run

    async def complete_shadow(
        self,
        candidate: PolicyCandidate,
        run: ShadowRun,
        reason: str = "sweep_completed",
    ) -> tuple[PolicyCandidate, ShadowRun]:
        """Mark shadow run complete and transition candidate to shadow_completed.

        Raises ValueError if run is not RUNNING or if run/candidate are mismatched.
        """
        if run.status != ShadowRunStatus.RUNNING:
            raise ValueError(
                f"ShadowRun {run.id!r} is already {run.status.value!r}, cannot complete again."
            )
        if run.candidate_id != candidate.id:
            raise ValueError(
                f"ShadowRun {run.id!r} belongs to candidate {run.candidate_id!r}, "
                f"not {candidate.id!r}."
            )
        now = self._now_iso()
        obs = run.observations_count
        match_rate = round(run.matched_count / obs, 4) if obs > 0 else 0.0
        fallback_rate = round(run.fallback_count / obs, 4) if obs > 0 else 0.0

        summary = {
            "observations": obs,
            "matched": run.matched_count,
            "fallback": run.fallback_count,
            "match_rate": match_rate,
            "fallback_rate": fallback_rate,
        }
        run = run.model_copy(update={
            "status": ShadowRunStatus.COMPLETED,
            "completed_at": now,
            "summary": summary,
        })
        await self._store.save_shadow_run(run)

        candidate = await self.transition(
            candidate,
            PolicyCandidateStatus.SHADOW_COMPLETED,
            actor_type=LifecycleActorType.SWEEP,
            reason=reason,
            metadata={"shadow_run_id": run.id, "summary": summary},
        )
        return candidate, run

    async def approve(
        self,
        candidate: PolicyCandidate,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> PolicyCandidate:
        """Transition candidate to approved_production."""
        from_status = candidate.status.value
        now = self._now_iso()
        candidate = candidate.model_copy(update={"approved_by": actor_id, "approved_at": now})
        updated = await self.transition(
            candidate,
            PolicyCandidateStatus.APPROVED_PRODUCTION,
            actor_type=LifecycleActorType.OPERATOR,
            actor_id=actor_id,
            reason=reason or "approved",
        )
        _fire_telemetry(
            _emit_telemetry_safe(updated, from_status, PolicyCandidateStatus.APPROVED_PRODUCTION.value, "operator")
        )
        return updated

    async def reject(
        self,
        candidate: PolicyCandidate,
        actor_id: str,
        reason: str,
    ) -> PolicyCandidate:
        """Transition candidate to rejected."""
        from_status = candidate.status.value
        candidate = candidate.model_copy(update={"rejection_reason": reason})
        updated = await self.transition(
            candidate,
            PolicyCandidateStatus.REJECTED,
            actor_type=LifecycleActorType.OPERATOR,
            actor_id=actor_id,
            reason=reason,
        )
        _fire_telemetry(
            _emit_telemetry_safe(updated, from_status, PolicyCandidateStatus.REJECTED.value, "operator")
        )
        return updated

    async def sweep(self) -> int:
        """Check shadow_running candidates; complete those meeting criteria.

        Returns count of candidates transitioned to shadow_completed.
        """
        candidates = await self._store.list_shadow_running_candidates()
        completed = 0
        for candidate in candidates:
            try:
                completed += await self._check_and_complete(candidate)
            except Exception:
                logger.exception(
                    "KAIROS sweep: error processing candidate %s",
                    candidate.id,
                )
        return completed

    async def _check_and_complete(self, candidate: PolicyCandidate) -> int:
        if not candidate.shadow_run_id:
            return 0

        run = await self._store.get_shadow_run(candidate.shadow_run_id)
        if run is None or run.status != ShadowRunStatus.RUNNING:
            return 0

        obs_met = run.observations_count >= self._settings.shadow_min_observations

        started = datetime.fromisoformat(run.started_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed_hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
        duration_met = elapsed_hours >= self._settings.shadow_duration_hours

        if not (obs_met or duration_met):
            return 0

        reason = "min_observations_reached" if obs_met else "duration_expired"
        candidate, completed_run = await self.complete_shadow(candidate, run, reason=reason)
        logger.info(
            "KAIROS sweep: completed shadow run for candidate %s (reason=%s, obs=%d)",
            candidate.id, reason, run.observations_count,
        )
        _fire_telemetry(
            _emit_telemetry_safe(candidate, PolicyCandidateStatus.SHADOW_RUNNING.value,
                                 PolicyCandidateStatus.SHADOW_COMPLETED.value, "sweep", completed_run)
        )
        return 1
