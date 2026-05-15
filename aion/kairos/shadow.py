"""KAIROS Shadow Evaluator — side-effect observer for shadow mode policy testing.

KairosShadowEvaluator runs as a fire-and-forget side-effect AFTER the pipeline
produces a response. It never modifies the response or blocks the request path.

For each active shadow_running candidate of the requesting tenant, the evaluator:
  1. Checks whether the request would have matched the candidate's trigger conditions.
  2. If matched: increments shadow_run.matched_count.
  3. If not matched: no counter change (only observations_count is incremented).
  4. Always increments shadow_run.observations_count.

Trigger condition fields supported (mapped from PipelineContext):
  - intent        → metadata["intent"] if present; else estixe_result.intent_category
  - risk_tier     → metadata["risk_tier"] if present; else nomos_result.risk_tier
  - decision      → context.decision.value (bypass|block|continue)
  - tenant        → context.tenant
  - pii_detected  → bool(metadata.get("pii_detected", False)) — always coerced to bool
  - <any>         → metadata[field] for arbitrary metadata keys

  Note: metadata takes priority over result objects for intent/risk_tier.
  This allows test overrides and manual metadata injection to shadow-test edge cases.

Integration: called from aion/pipeline.py at the end of Pipeline.run_post() via
asyncio.create_task(_guarded_bg(evaluator.evaluate(context_snapshot, response))).

Note: pipeline.py passes a shallow context snapshot (metadata dict copied) to protect
against post-pipeline mutations in asyncio coroutines that resume before this task runs.

Note on tenant="default": AION is deployed single-tenant per instance (on-prem). The
value "default" is a legitimate tenant identifier when no explicit tenant is configured.
The evaluator does NOT reject "default" — operators must ensure correct tenant routing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aion.shared.schemas import ChatCompletionResponse, PipelineContext

from aion.kairos.models import PolicyCandidate, ShadowRunStatus, TriggerCondition

logger = logging.getLogger("aion.kairos.shadow")


# ── Trigger condition evaluation ──────────────────────────────────────────────


def _extract_context_value(field: str, context: "PipelineContext") -> Any:
    """Extract a named field from PipelineContext for trigger evaluation."""
    # pii_detected is always bool regardless of how it was stored in metadata
    if field == "pii_detected":
        return bool(context.metadata.get("pii_detected", False))

    # Direct metadata lookup first
    if field in context.metadata:
        return context.metadata[field]

    # Well-known AION pipeline fields
    if field == "intent":
        result = getattr(context, "estixe_result", None)
        if result is not None:
            return getattr(result, "intent_category", None)
        return context.metadata.get("intent")

    if field == "risk_tier":
        result = getattr(context, "nomos_result", None)
        if result is not None:
            return getattr(result, "risk_tier", None)
        return context.metadata.get("risk_tier")

    if field == "decision":
        return context.decision.value if context.decision else None

    if field == "tenant":
        return context.tenant

    return None


def _evaluate_condition(condition: TriggerCondition, context: "PipelineContext") -> bool:
    """Evaluate a single trigger condition against the pipeline context.

    Returns True if the condition is satisfied.
    """
    actual = _extract_context_value(condition.field, context)
    expected = condition.value
    op = condition.operator

    if actual is None:
        return False

    try:
        if op == "equals":
            return str(actual).lower() == str(expected).lower()

        if op == "not_equals":
            return str(actual).lower() != str(expected).lower()

        if op == "contains":
            return str(expected).lower() in str(actual).lower()

        if op == "in":
            values = expected if isinstance(expected, list) else [expected]
            return str(actual).lower() in [str(v).lower() for v in values]

        if op == "matches_pattern":
            pattern = str(expected)
            return bool(re.search(pattern, str(actual), re.IGNORECASE))

        if op in ("gte", "lte"):
            actual_float = float(actual)
            expected_float = float(expected)
            return actual_float >= expected_float if op == "gte" else actual_float <= expected_float

    except (ValueError, TypeError, re.error):
        logger.debug(
            "KAIROS shadow: condition evaluation failed (field=%s op=%s): skipping",
            condition.field, op,
        )

    return False


def _candidate_matches(candidate: PolicyCandidate, context: "PipelineContext") -> bool:
    """Return True if ALL trigger conditions of the candidate match the context.

    Empty trigger_conditions → always match (unconditional shadow observation).
    """
    if not candidate.trigger_conditions:
        return True
    return all(_evaluate_condition(c, context) for c in candidate.trigger_conditions)


# ── KairosShadowEvaluator ─────────────────────────────────────────────────────


class KairosShadowEvaluator:
    """Fire-and-forget observer that records shadow run counters post-pipeline.

    Usage (in pipeline.py):
        ctx_snap = context.model_copy(update={
            "metadata": dict(context.metadata),
            "module_latencies": dict(context.module_latencies),
        })
        task = asyncio.create_task(_guarded_bg(evaluator.evaluate(ctx_snap, response)))
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
    """

    async def evaluate(
        self,
        context: "PipelineContext",
        response: Optional["ChatCompletionResponse"] = None,
    ) -> None:
        """Evaluate all active shadow candidates for the request's tenant.

        Catches exceptions around get_kairos(), list_candidates(), and
        per-candidate observation (via asyncio.gather return_exceptions=True).
        Other unforeseen failures rely on the surrounding _guarded_bg wrapper.
        """
        from aion.kairos import get_kairos

        try:
            kairos = get_kairos()
        except Exception:
            logger.debug("KAIROS shadow: module unavailable (non-critical)", exc_info=True)
            return

        tenant_id = context.tenant
        if not tenant_id:
            return

        try:
            candidates = await kairos.store.list_shadow_running_candidates(tenant_id)
        except Exception:
            logger.warning("KAIROS shadow: failed to list candidates for %s", tenant_id, exc_info=True)
            return

        # Defense-in-depth: skip any candidate that doesn't belong to this tenant
        own = [c for c in candidates if c.tenant_id == tenant_id]

        # Observe all candidates concurrently — each _observe is independent
        results = await asyncio.gather(
            *[self._observe(c, context, kairos) for c in own],
            return_exceptions=True,
        )
        for i, exc in enumerate(results):
            if isinstance(exc, BaseException):
                logger.warning(
                    "KAIROS shadow: error observing candidate %s",
                    own[i].id,
                    exc_info=exc,
                )

    async def _observe(
        self,
        candidate: PolicyCandidate,
        context: "PipelineContext",
        kairos: Any,
    ) -> None:
        """Record one observation for a candidate's shadow run."""
        if not candidate.shadow_run_id:
            return

        run = await kairos.store.get_shadow_run(candidate.shadow_run_id)
        if run is None or run.status != ShadowRunStatus.RUNNING:
            return

        matched = 1 if _candidate_matches(candidate, context) else 0
        await kairos.store.increment_shadow_counters(
            run.id,
            matched=matched,
            fallback=0,
            observations=1,
        )

        logger.debug(
            "KAIROS shadow: candidate=%s run=%s matched=%s",
            candidate.id, run.id, bool(matched),
        )
