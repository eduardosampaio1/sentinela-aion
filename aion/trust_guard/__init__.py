"""AION Trust Guard — License & Integrity Control Plane.

Public API used by main.py:

  await startup_validation() → TrustState
  start_trust_guard_loop(pipeline) → asyncio.Task

The Trust Guard validates license authenticity, verifies build integrity via
the Sentinela Artifact Signing Key, and (in Phase 2) sends optional heartbeat
signals to the Sentinela Control Plane to receive entitlement updates.

All failures are logged and handled gracefully — Trust Guard issues must never
crash AION or interrupt client traffic.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger("aion.trust_guard")


async def startup_validation() -> "TrustState":
    """Validate license + integrity at boot. Returns TrustState.

    Called from main.py:lifespan AFTER validate_license_or_abort()
    and BEFORE build_pipeline(). Does NOT make any HTTP calls — startup
    must remain fast regardless of network availability.
    """
    from aion.trust_guard.trust_state import (
        TrustState, TrustStates, IntegrityStatus,
        load_trust_state, save_trust_state,
    )
    from aion.trust_guard.license_authority import get_license_claims, build_initial_trust_state
    from aion.trust_guard.integrity_manifest import verify_manifest
    from aion.trust_guard.audit_emitter import emit_trust_event
    from aion.config import get_trust_guard_settings
    from aion import __version__

    settings = get_trust_guard_settings()

    if not settings.enabled:
        logger.debug("trust_guard: disabled (AION_TRUST_GUARD_ENABLED=false)")
        return TrustState()

    # ── Step 1: Load cached state (fallback if anything fails below) ──────────
    cached = load_trust_state()

    # ── Step 2: Get license claims ────────────────────────────────────────────
    try:
        claims = get_license_claims()
    except Exception as e:
        logger.debug("trust_guard: get_license_claims failed: %s", e)
        return cached

    # ── Step 3: Determine build_id from manifest (before full verification) ───
    build_id = _get_build_id()

    # ── Step 4: Build initial state from license ──────────────────────────────
    state = build_initial_trust_state(claims, build_id, __version__)

    # ── Step 5: Verify integrity manifest ────────────────────────────────────
    try:
        integrity_result = verify_manifest()
        if integrity_result.verified:
            state.integrity_status = IntegrityStatus.VERIFIED
            if integrity_result.build_id:
                state.build_id = integrity_result.build_id
            emit_trust_event(
                "trust.integrity_verified",
                tenant_id=state.tenant_id or "system",
                build_id=state.build_id,
                aion_version=state.aion_version,
                files_count=7,
            )
        else:
            state.integrity_status = IntegrityStatus.TAMPERED
            state.trust_state = TrustStates.TAMPERED
            state.state_reason = integrity_result.reason
            state.files_diverged = integrity_result.files_diverged
            emit_trust_event(
                "trust.integrity_failed",
                tenant_id=state.tenant_id or "system",
                build_id=state.build_id,
                reason=integrity_result.reason,
                files_diverged=",".join(integrity_result.files_diverged),
            )
    except Exception as e:
        logger.debug("trust_guard: integrity check failed (non-fatal): %s", e)
        state.integrity_status = IntegrityStatus.UNVERIFIED

    # ── Step 6: Emit license audit event ─────────────────────────────────────
    try:
        _emit_license_event(state, claims)
    except Exception as e:
        logger.debug("trust_guard: license audit event failed: %s", e)

    # ── Step 7: Emit state transition if changed from cache ───────────────────
    if cached.trust_state != state.trust_state:
        emit_trust_event(
            "trust.state_transition",
            tenant_id=state.tenant_id or "system",
            from_state=cached.trust_state,
            to_state=state.trust_state,
            reason=state.state_reason,
        )

    # ── Step 8: Persist ───────────────────────────────────────────────────────
    try:
        save_trust_state(state)
    except Exception as e:
        logger.debug("trust_guard: save_trust_state failed: %s", e)

    _log_startup_summary(state)
    return state


def start_trust_guard_loop(pipeline) -> asyncio.Task:
    """Start the background Trust Guard loop. Returns a cancellable asyncio.Task.

    First iteration runs immediately (within seconds of startup).
    Subsequent iterations sleep heartbeat_interval seconds.
    All exceptions are caught — loop crash must not propagate to AION.
    """
    return asyncio.create_task(_trust_guard_loop(pipeline))


async def _trust_guard_loop(pipeline) -> None:
    """Background loop: heartbeat (Phase 2) + periodic state refresh."""
    from aion.config import get_trust_guard_settings

    settings = get_trust_guard_settings()
    if not settings.enabled:
        return

    # First iteration: immediate (apply any cached entitlement state)
    await _run_trust_cycle(pipeline)

    while True:
        try:
            await asyncio.sleep(settings.heartbeat_interval)
            await _run_trust_cycle(pipeline)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("trust_guard: loop iteration failed (non-fatal): %s", e)


async def _run_trust_cycle(pipeline) -> None:
    """Single trust cycle: heartbeat (if configured) + apply entitlement."""
    from aion.trust_guard.trust_state import load_trust_state
    from aion.trust_guard.entitlement_engine import EntitlementEngine, TrustViolationBehavior
    from aion.config import get_trust_guard_settings

    settings = get_trust_guard_settings()
    state = load_trust_state()

    # Heartbeat: send operational signal, apply server entitlement if configured
    heartbeat_url = _get_heartbeat_url(state)
    if heartbeat_url:
        state = await _do_heartbeat(state, heartbeat_url, settings.grace_hours)

    # Apply entitlement based on current state
    try:
        behavior = TrustViolationBehavior(settings.violation_behavior)
        EntitlementEngine.apply(pipeline, state, behavior)
    except Exception as e:
        logger.debug("trust_guard: EntitlementEngine.apply failed: %s", e)


async def _do_heartbeat(state, heartbeat_url: str, grace_hours: int) -> "TrustState":
    """Delegate to HeartbeatReporter. Catches all exceptions — loop must never crash."""
    try:
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        return await HeartbeatReporter.report(state, heartbeat_url, grace_hours)
    except Exception as e:
        logger.debug("trust_guard: _do_heartbeat unexpected error: %s", e)
        return state


def _get_heartbeat_url(state) -> str:
    """Return effective heartbeat URL: env override > JWT claim stored in TrustState."""
    import os
    return (
        os.environ.get("AION_TRUST_GUARD_SERVER_URL", "").strip()
        or getattr(state, "heartbeat_url", "")
        or ""
    )


def _get_build_id() -> str:
    """Read build_id from the integrity manifest (if present) or env."""
    import os
    env_build_id = os.environ.get("AION_BUILD_ID", "").strip()
    if env_build_id:
        return env_build_id

    try:
        from aion.trust_guard.integrity_manifest import _MANIFEST_PATH
        import json
        if _MANIFEST_PATH.exists():
            manifest = json.loads(_MANIFEST_PATH.read_bytes())
            return manifest.get("build_id", "")
    except Exception:
        pass
    return ""


def _emit_license_event(state, claims: dict) -> None:
    from aion.trust_guard.audit_emitter import emit_trust_event
    from aion.trust_guard.trust_state import TrustStates

    if state.trust_state == TrustStates.INVALID:
        emit_trust_event(
            "trust.license_invalid",
            tenant_id=state.tenant_id or "system",
            reason=state.state_reason,
        )
    else:
        emit_trust_event(
            "trust.license_validated",
            tenant_id=state.tenant_id or "system",
            license_id=state.license_id,
            tier=claims.get("tier", ""),
            expires_at=str(claims.get("expires_at", "")),
        )

    if state.trust_state in {TrustStates.GRACE}:
        emit_trust_event(
            "trust.grace_period_warning",
            tenant_id=state.tenant_id or "system",
            hours_until_restricted=str(state.grace_hours_remaining or ""),
            reason=state.state_reason,
        )

    if state.trust_state == TrustStates.RESTRICTED:
        emit_trust_event(
            "trust.restricted_mode",
            tenant_id=state.tenant_id or "system",
            frozen_features="nemos_writes,nomos_advanced,metis",
            reason=state.state_reason,
        )


def _log_startup_summary(state) -> None:
    from aion.trust_guard.trust_state import TrustStates

    if state.trust_state == TrustStates.ACTIVE:
        logger.info(
            "Trust Guard: ACTIVE | tenant=%s | build=%s | integrity=%s",
            state.tenant_id, state.build_id, state.integrity_status,
        )
    elif state.trust_state == TrustStates.GRACE:
        logger.warning(
            "Trust Guard: GRACE | tenant=%s | %.0fh until restricted",
            state.tenant_id, state.grace_hours_remaining or 0,
        )
    elif state.trust_state == TrustStates.TAMPERED:
        logger.warning(
            "Trust Guard: TAMPERED | files_diverged=%s | violation_behavior=%s",
            state.files_diverged,
            state.state_reason,
        )
    else:
        logger.warning(
            "Trust Guard: %s | tenant=%s | reason=%s",
            state.trust_state, state.tenant_id, state.state_reason,
        )
