"""Pipeline orchestrator — assembles the module chain based on active config.

Supports:
- SAFE_MODE: bypass all modules, pure passthrough
- Per-component degradation: if a module fails, only that module is disabled
- Health status per module
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Protocol, runtime_checkable

from aion.config import FailMode, get_settings
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Decision,
    PipelineContext,
)
from aion.shared.telemetry import TelemetryEvent, emit

logger = logging.getLogger("aion.pipeline")

# Strong references to fire-and-forget background tasks — prevents GC before completion.
_BG_TASKS: set[asyncio.Task] = set()


async def _guarded_bg(coro, *, timeout: float | None = None) -> None:
    """Wrap a fire-and-forget coroutine with a timeout to prevent indefinite hangs."""
    if timeout is None:
        timeout = get_settings().bg_task_timeout_seconds
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.debug("_guarded_bg: coroutine timed out after %.1fs", timeout)
    except Exception:
        logger.debug("_guarded_bg: coroutine raised exception (swallowed)", exc_info=True)


@runtime_checkable
class Module(Protocol):
    """Interface that every AION module must implement."""

    name: str

    async def process(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        """Process the request. May modify context.modified_request or set bypass/block."""
        ...


class ModuleStatus:
    """Tracks health status of a single module."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.healthy = True
        self.consecutive_failures = 0
        self.last_failure_reason: str = ""
        # threshold is intentionally NOT cached here — read dynamically so that
        # changes to AION_MODULE_FAILURE_THRESHOLD take effect without restart

    def record_success(self) -> None:
        self.consecutive_failures = 0
        if not self.healthy:
            self.healthy = True
            logger.info(
                '{"event":"module_recovered","module":"%s"}', self.name,
            )

    def record_failure(self, reason: str) -> None:
        self.consecutive_failures += 1
        self.last_failure_reason = reason
        threshold = get_settings().module_failure_threshold
        if self.consecutive_failures >= threshold and self.healthy:
            self.healthy = False
            logger.warning(
                '{"event":"module_degraded","module":"%s","failures":%d,"reason":"%s"}',
                self.name, self.consecutive_failures, reason[:100],
            )


# ── Telemetry metadata whitelist ──
# Campos dinamicos de context.metadata que vao para /v1/events.
# Mantem schema previsivel mas expoe sinais importantes do ESTIXE.
_TELEMETRY_ESTIXE_KEYS = (
    # Velocity (rolling-window block counter)
    "velocity_alert", "velocity_recent_blocks",
    # Shadow mode (categoria em observacao, nao bloqueia)
    "shadow_risk_category", "shadow_risk_level", "shadow_risk_confidence",
    "shadow_risk_matched_seed",
    # Flagged (risk_level=medium, FLAG + CONTINUE)
    "flagged_risk_category", "flagged_risk_confidence", "flagged_risk_matched_seed",
    "flagged_risk_source",
    # Detected (risk_level critical/high que bloqueou)
    "detected_risk_category", "risk_level", "risk_confidence",
    "risk_matched_seed", "risk_threshold_used", "risk_source",
    # Output guard
    "output_risk_category", "output_risk_confidence",
    # PII
    "pii_violations", "pii_audited",
    # Intent
    "detected_intent", "intent_confidence",
)


def _build_telemetry_metadata(context) -> dict:
    """Build telemetry metadata, including dynamic ESTIXE signals from context."""
    md = {
        "module_latencies": context.module_latencies,
        "safe_mode": context.metadata.get("safe_mode", False),
        "skipped_modules": context.metadata.get("skipped_modules", []),
        "failed_modules": context.metadata.get("failed_modules", []),
        "complexity_score": context.metadata.get("complexity_score", 0),
        "route_reason": context.metadata.get("route_reason", ""),
    }
    # Include ESTIXE dynamic signals when present — skip absent to keep payload lean
    for key in _TELEMETRY_ESTIXE_KEYS:
        if key in context.metadata:
            md[key] = context.metadata[key]
    return md


class Pipeline:
    """Dynamically assembles and runs the module chain."""

    # Redis key for the persisted kill switch state (N5 fix). Survives process
    # restarts so an active killswitch isn't silently dropped on deploy/crash.
    _KILLSWITCH_REDIS_KEY = "aion:pipeline:killswitch"

    def __init__(self) -> None:
        self._pre_modules: list[Module] = []
        self._post_modules: list[Module] = []
        self._module_status: dict[str, ModuleStatus] = {}
        self._safe_mode = False
        self._safe_mode_reason: str = ""
        # Unix timestamp (seconds) when the kill switch should auto-deactivate.
        # None = no TTL, killswitch stays active until manually deactivated.
        self._safe_mode_expires_at: Optional[float] = None

    def register_pre(self, module: Module) -> None:
        self._pre_modules.append(module)
        self._module_status[module.name] = ModuleStatus(module.name)
        logger.info("Registered pre-LLM module: %s", module.name)

    def register_post(self, module: Module) -> None:
        self._post_modules.append(module)
        key = f"{module.name}_post"
        self._module_status[key] = ModuleStatus(key)
        logger.info("Registered post-LLM module: %s", module.name)

    @property
    def active_modules(self) -> list[str]:
        return [m.name for m in self._pre_modules + self._post_modules]

    def _expire_safe_mode_if_needed(self) -> None:
        """Internal: lazy TTL check — invoked by is_safe_mode and safe_mode_state.

        Single source of truth for the auto-deactivate logic so we don't
        diverge between `is_safe_mode()` (called on hot path) and the read of
        `safe_mode_state` (called by the /v1/killswitch GET handler).
        """
        if self._safe_mode and self._safe_mode_expires_at is not None:
            if time.time() >= self._safe_mode_expires_at:
                self.deactivate_safe_mode()

    @property
    def is_safe_mode(self) -> bool:
        self._expire_safe_mode_if_needed()
        return self._safe_mode

    def _log_mode_transition(self, from_mode: str, to_mode: str, reason: str, actor: str = "system") -> None:
        """Emit structured mode transition event."""
        logger.warning(
            '{"event":"mode_transition","from":"%s","to":"%s","reason":"%s","actor":"%s"}',
            from_mode, to_mode, reason, actor,
        )

    def activate_safe_mode(self, reason: str = "manual", expires_at: Optional[float] = None) -> None:
        """Kill switch — disable all modules, pure passthrough.

        Args:
            reason: free-text reason recorded for auditing.
            expires_at: optional Unix timestamp (seconds since epoch) when the
                kill switch should auto-deactivate. The pipeline checks this on
                every `is_safe_mode()` call. None = stays active until manual
                deactivation.

        State is persisted to Redis (fire-and-forget) so a process restart
        doesn't silently lose the killswitch (N5 fix). On boot, call
        `restore_safe_mode_from_redis()` to rehydrate.
        """
        prev_mode = "degraded" if any(not s.healthy for s in self._module_status.values()) else "normal"
        self._safe_mode = True
        self._safe_mode_reason = reason
        self._safe_mode_expires_at = expires_at
        self._log_mode_transition(prev_mode, "safe", reason)
        # Persist to Redis without blocking the caller. Best-effort — failures
        # are logged at debug to avoid breaking the kill switch UX if Redis
        # is unavailable (the in-memory state still works for this process).
        asyncio.create_task(self._persist_safe_mode_to_redis())

    def deactivate_safe_mode(self) -> None:
        """Recover from safe mode."""
        self._safe_mode = False
        self._safe_mode_reason = ""
        self._safe_mode_expires_at = None
        self._log_mode_transition("safe", "normal", "manual_recovery")
        asyncio.create_task(self._clear_safe_mode_in_redis())

    @property
    def safe_mode_state(self) -> dict:
        """Snapshot of the kill switch state for the /v1/killswitch endpoint.

        Reads `is_safe_mode` (which triggers the lazy TTL check) so the
        snapshot reflects whatever state the next pipeline pass would see.
        """
        active = self.is_safe_mode  # honors TTL via _expire_safe_mode_if_needed
        return {
            "killswitch_active": active,
            "reason": self._safe_mode_reason or None,
            "expires_at": self._safe_mode_expires_at,
        }

    # ── Redis persistence (N5 fix) ──────────────────────────────────────────
    async def _persist_safe_mode_to_redis(self) -> None:
        """Best-effort write of the current killswitch state to Redis."""
        try:
            from aion.metis.behavior import _get_redis  # reuse existing client
            r = await _get_redis()
            if not r:
                return
            import json as _json
            payload = _json.dumps({
                "reason": self._safe_mode_reason,
                "expires_at": self._safe_mode_expires_at,
            })
            # If a TTL was configured, mirror it on the Redis key so a stale
            # process never restores an already-expired state.
            if self._safe_mode_expires_at is not None:
                ttl_seconds = int(self._safe_mode_expires_at - time.time())
                if ttl_seconds > 0:
                    await r.setex(self._KILLSWITCH_REDIS_KEY, ttl_seconds, payload)
                else:
                    await r.delete(self._KILLSWITCH_REDIS_KEY)
            else:
                await r.set(self._KILLSWITCH_REDIS_KEY, payload)
        except Exception:
            logger.debug("Killswitch persist to Redis failed (non-fatal)", exc_info=True)

    async def _clear_safe_mode_in_redis(self) -> None:
        """Best-effort delete of the persisted killswitch state."""
        try:
            from aion.metis.behavior import _get_redis
            r = await _get_redis()
            if r:
                await r.delete(self._KILLSWITCH_REDIS_KEY)
        except Exception:
            logger.debug("Killswitch clear in Redis failed (non-fatal)", exc_info=True)

    async def restore_safe_mode_from_redis(self) -> None:
        """Rehydrate the killswitch state on boot.

        Called once during application startup. If Redis is unavailable this
        is a no-op and the pipeline starts in normal mode (matching legacy
        behavior). If a TTL had been configured and has already elapsed during
        downtime, we clear the stale key and stay in normal mode.
        """
        try:
            from aion.metis.behavior import _get_redis
            r = await _get_redis()
            if not r:
                return
            raw = await r.get(self._KILLSWITCH_REDIS_KEY)
            if not raw:
                return
            import json as _json
            data = _json.loads(raw)
            expires_at = data.get("expires_at")
            if expires_at is not None and time.time() >= float(expires_at):
                await r.delete(self._KILLSWITCH_REDIS_KEY)
                logger.info("Killswitch state in Redis was already expired — discarded")
                return
            self._safe_mode = True
            self._safe_mode_reason = str(data.get("reason") or "")
            self._safe_mode_expires_at = float(expires_at) if expires_at is not None else None
            self._log_mode_transition("normal", "safe", f"restored_from_redis: {self._safe_mode_reason}")
            logger.warning(
                "Killswitch RESTORED from Redis on boot — reason=%r expires_at=%s",
                self._safe_mode_reason,
                self._safe_mode_expires_at,
            )
        except Exception:
            logger.warning("Failed to restore killswitch state from Redis (non-fatal)", exc_info=True)

    def get_health(self) -> dict:
        """Get health status per module."""
        if self._safe_mode:
            return {
                "mode": "safe",
                "safe_mode_reason": self._safe_mode_reason,
                "modules": {
                    name: "bypassed" for name in self._module_status
                },
            }

        module_health = {}
        for name, status in self._module_status.items():
            if status.healthy:
                module_health[name] = "ok"
            else:
                module_health[name] = "degraded"

        degraded = [n for n, s in self._module_status.items() if not s.healthy]
        if degraded:
            mode = "degraded"
        else:
            mode = "normal"

        return {
            "mode": mode,
            "modules": module_health,
            "degraded_components": degraded,
        }

    def get_degraded_headers(self) -> dict[str, str]:
        """Build degradation headers for the response."""
        health = self.get_health()
        headers: dict[str, str] = {}

        if health["mode"] == "safe":
            headers["X-Aion-Degraded"] = "true"
            headers["X-Aion-Degraded-Components"] = "all"
            headers["X-Aion-Degraded-Impact"] = "passthrough"
        elif health["mode"] == "degraded":
            degraded = health.get("degraded_components", [])
            headers["X-Aion-Degraded"] = "true"
            headers["X-Aion-Degraded-Components"] = ",".join(degraded)
            # Map components to impact
            impacts = []
            for comp in degraded:
                if "estixe" in comp:
                    impacts.append("bypass_disabled")
                if "nomos" in comp:
                    impacts.append("routing_fallback")
                if "metis" in comp:
                    impacts.append("optimization_disabled")
            headers["X-Aion-Degraded-Impact"] = ",".join(impacts) if impacts else "partial"

        return headers

    async def run_pre(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        """Run pre-LLM modules. May result in bypass or block."""
        context.original_request = request
        context.modified_request = request.model_copy(deep=True)

        # Tenant isolation: ensure context.tenant is set and immutable for this run
        if not context.tenant:
            context.tenant = "default"
        _tenant_for_run = context.tenant  # captured — cannot be changed by modules

        # SAFE_MODE: skip everything
        if self._safe_mode:
            context.metadata["safe_mode"] = True
            return context

        # ── Multi-turn context: load last 3 turns (fail-open) ──
        settings = get_settings()
        if settings.multi_turn_context and context.session_id:
            try:
                from aion.shared.turn_context import get_turn_context_store
                turn_ctx = await get_turn_context_store().load(context.tenant, context.session_id)
                if turn_ctx:
                    context.metadata["turn_context"] = turn_ctx
            except Exception:
                logger.debug("Multi-turn context load failed (non-critical)", exc_info=True)

        # ── Semantic Cache: early exit (before any module) ──
        try:
            from aion.cache import get_cache
            cache = get_cache()
            if cache.enabled:
                import time as _time
                t0 = _time.perf_counter()
                cached_response = cache.lookup(request, context)
                elapsed_ms = (_time.perf_counter() - t0) * 1000
                context.module_latencies["cache"] = round(elapsed_ms, 2)

                if cached_response is not None:
                    context.set_bypass(cached_response)
                    context.metadata["cache_hit"] = True
                    context.metadata["cache_response_id"] = cached_response.id
                    return context
                else:
                    context.metadata["cache_hit"] = False
        except Exception:
            logger.warning("Cache lookup failed — continuing pipeline", exc_info=True)
            context.metadata["cache_hit"] = False

        for module in self._pre_modules:
            if context.decision != Decision.CONTINUE:
                break

            # Skip degraded modules (per-component degradation)
            status = self._module_status.get(module.name)
            if status and not status.healthy:
                logger.debug("Skipping degraded module: %s", module.name)
                context.metadata.setdefault("skipped_modules", []).append(module.name)
                continue

            t0 = time.perf_counter()
            try:
                context = await module.process(context.modified_request, context)
                if status:
                    status.record_success()
            except Exception as exc:
                logger.exception("Module %s failed", module.name)
                if status:
                    status.record_failure(str(exc))

                if settings.fail_mode == FailMode.CLOSED:
                    context.set_block(f"Module {module.name} failed (fail-closed)")
                    break
                # fail-open: skip this module, continue to next
                logger.warning("Fail-open: skipping %s, continuing pipeline", module.name)
                context.metadata.setdefault("failed_modules", []).append(module.name)
                continue
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                context.module_latencies[module.name] = round(elapsed_ms, 2)

            # Per-module tenant isolation check — stops subsequent modules from running
            # with a compromised tenant value if a module attempted injection.
            if context.tenant != _tenant_for_run:
                logger.error(
                    "TENANT ISOLATION VIOLATION: module '%s' changed tenant from '%s' to '%s' — blocking request",
                    module.name, _tenant_for_run, context.tenant,
                )
                context.tenant = _tenant_for_run
                context.decision = Decision.BLOCK
                context.metadata["block_reason"] = "tenant_isolation_violation"
                context.metadata["violating_module"] = module.name
                break

        # Note: tenant isolation is enforced per-module inside the loop above.

        # ── Multi-turn context + session audit: save current turn (fire-and-forget) ──
        if settings.multi_turn_context and context.session_id:
            try:
                from aion.shared.turn_context import TurnSummary, TurnContext, get_turn_context_store
                from aion.shared.session_audit import TurnAuditEntry, _hash_message, get_session_audit_store

                now = time.time()
                intent = context.metadata.get("detected_intent")
                complexity = float(context.metadata.get("complexity_score", 0.0))
                pii_types = list(context.metadata.get("pii_violations", []))
                risk_score = float(context.metadata.get("risk_confidence", 0.0))
                decision_val = context.decision.value
                policies = []
                if context.estixe_result:
                    policies = list(getattr(context.estixe_result, "policy_matched", []))

                # TurnContext (session state for pipeline decisions)
                turn = TurnSummary(
                    intent=intent,
                    complexity=complexity,
                    model_used=context.selected_model or "",
                    pii_types=pii_types,
                    risk_score=risk_score,
                    decision=decision_val,
                    timestamp=now,
                )
                turn_ctx = context.metadata.get("turn_context") or TurnContext(
                    session_id=context.session_id, tenant=context.tenant
                )
                turn_ctx.add_turn(turn)
                _t1 = asyncio.create_task(_guarded_bg(get_turn_context_store().save(context.tenant, turn_ctx)))
                _BG_TASKS.add(_t1)
                _t1.add_done_callback(_BG_TASKS.discard)

                # TurnAuditEntry (session audit trail for compliance)
                req = context.original_request
                last_user_content = None
                if req and req.messages:
                    for m in reversed(req.messages):
                        if getattr(m, "role", "") == "user":
                            last_user_content = getattr(m, "content", None)
                            break
                audit_entry = TurnAuditEntry(
                    request_id=context.request_id,
                    timestamp=now,
                    user_message_hash=_hash_message(last_user_content),
                    decision=decision_val,
                    model_used=context.selected_model,
                    pii_types_detected=pii_types,
                    risk_score=risk_score,
                    intent_detected=intent,
                    policies_matched=policies,
                    tokens_sent=context.tokens_after,
                    tokens_received=0,  # populated post-LLM if available
                    latency_ms=sum(context.module_latencies.values()),
                )
                _t2 = asyncio.create_task(_guarded_bg(
                    get_session_audit_store().append_turn(context.tenant, context.session_id, audit_entry)
                ))
                _BG_TASKS.add(_t2)
                _t2.add_done_callback(_BG_TASKS.discard)
            except Exception:
                logger.debug("Multi-turn context/audit save failed (non-critical)", exc_info=True)

        # ── Cross-tenant learning (opt-in) ──
        if settings.contribute_global_learning:
            try:
                estixe_result = context.estixe_result
                intent_cat = getattr(estixe_result, "intent_detected", None) if estixe_result else None
                risk_score = context.metadata.get("risk_confidence", 0.0)
                risk_tier = context.metadata.get("risk_level", "none") or "none"
                complexity = context.nomos_result.complexity_score if context.nomos_result else 0.0
                decision = context.decision.value if context.decision else "continue"
                from aion.nemos.global_model import get_global_contributor
                _t3 = asyncio.create_task(_guarded_bg(
                    get_global_contributor().record(
                        context.tenant, intent_cat, risk_tier, complexity, decision
                    )
                ))
                _BG_TASKS.add(_t3)
                _t3.add_done_callback(_BG_TASKS.discard)
            except Exception:
                logger.debug("Global learning contribution failed (non-critical)", exc_info=True)

        return context

    async def run_post(
        self,
        response: ChatCompletionResponse,
        context: PipelineContext,
    ) -> ChatCompletionResponse:
        """Run post-LLM modules on the response."""
        # SAFE_MODE: skip everything
        if self._safe_mode:
            return response

        settings = get_settings()

        for module in self._post_modules:
            key = f"{module.name}_post"
            status = self._module_status.get(key)

            # Skip degraded post-modules
            if status and not status.healthy:
                logger.debug("Skipping degraded post-module: %s", module.name)
                continue

            t0 = time.perf_counter()
            try:
                context.metadata["llm_response"] = response
                context = await module.process(context.modified_request, context)
                response = context.metadata.get("llm_response", response)
                if status:
                    status.record_success()
            except Exception as exc:
                logger.exception("Post-module %s failed", module.name)
                if status:
                    status.record_failure(str(exc))
                if settings.fail_mode == FailMode.CLOSED:
                    break
                continue
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                context.module_latencies[key] = round(elapsed_ms, 2)

        # ── KAIROS shadow evaluation (fire-and-forget, never blocks response) ──
        # Snapshot the two mutable dicts (metadata, module_latencies) so post-pipeline
        # writes don't race with shadow evaluation. Result objects (estixe_result,
        # nomos_result) are treated as immutable after pipeline modules complete.
        try:
            from aion.kairos.shadow import KairosShadowEvaluator
            _ctx_snap = context.model_copy(update={
                "metadata": dict(context.metadata),
                "module_latencies": dict(context.module_latencies),
            })
            _t_shadow = asyncio.create_task(
                _guarded_bg(KairosShadowEvaluator().evaluate(_ctx_snap, response))
            )
            _BG_TASKS.add(_t_shadow)
            _t_shadow.add_done_callback(_BG_TASKS.discard)
        except Exception:
            logger.debug("KAIROS shadow evaluator setup failed (non-critical)", exc_info=True)

        return response

    async def emit_telemetry(self, context: PipelineContext) -> None:
        """Emit telemetry event for the completed pipeline run."""
        decision_str = context.decision.value
        module_that_decided = "pipeline"

        for module_name, _ in context.module_latencies.items():
            if context.decision != Decision.CONTINUE:
                module_that_decided = module_name.replace("_post", "")
                break

        total_latency = sum(context.module_latencies.values())

        # Calculate cost_saved if NOMOS routed to a different model
        cost_saved = 0.0
        estimated_cost = context.metadata.get("estimated_cost", 0.0)
        if context.selected_model and estimated_cost > 0:
            # cost_saved is the difference vs the default model
            cost_saved = max(0.0, context.metadata.get("default_cost", 0.0) - estimated_cost)

        tokens_saved = max(0, context.tokens_before - context.tokens_after)

        # Extrai o texto da última mensagem do usuário para exibição no console
        input_text = ""
        req = context.original_request or context.modified_request
        if req and req.messages:
            user_msgs = [m for m in req.messages if getattr(m, "role", "") == "user"]
            if user_msgs:
                content = getattr(user_msgs[-1], "content", "")
                input_text = str(content)[:200] if content else ""

        event = TelemetryEvent(
            event_type=decision_str,
            module=module_that_decided,
            request_id=context.request_id,
            decision=decision_str,
            model_used=context.selected_model or "",
            tokens_saved=tokens_saved,
            cost_saved=cost_saved,
            latency_ms=round(total_latency, 2),
            tenant=context.tenant,
            input_text=input_text,
            metadata=_build_telemetry_metadata(context),
        )
        await emit(event)


def build_pipeline() -> Pipeline:
    """Build the pipeline based on current settings."""
    settings = get_settings()
    pipeline = Pipeline()

    # Check if SAFE_MODE is on via env
    if settings.safe_mode:
        pipeline.activate_safe_mode("env_config")
        logger.warning("AION starting in SAFE_MODE — all modules bypassed")
        return pipeline

    if settings.estixe_enabled:
        from aion.estixe import get_module as get_estixe
        pipeline.register_pre(get_estixe())

    if settings.nomos_enabled:
        from aion.nomos import get_module as get_nomos
        pipeline.register_pre(get_nomos())

    if settings.metis_enabled:
        from aion.metis import get_module as get_metis_pre, get_post_module as get_metis_post
        pipeline.register_pre(get_metis_pre())
        pipeline.register_post(get_metis_post())

    logger.info("Pipeline built with modules: %s", pipeline.active_modules)
    return pipeline
