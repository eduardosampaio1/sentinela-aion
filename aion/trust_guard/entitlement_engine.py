"""AION Trust Guard — Entitlement Engine.

Maps TrustState → module capabilities. Uses the existing pipeline
ModuleStatus.healthy interface — no new concepts, no new infrastructure.

Behavior per state:

  ACTIVE      → all modules healthy (restore if previously restricted)
  GRACE       → no module impact (warning only, visible in /health)
  RESTRICTED  → NEMOS writes frozen; module toggles unchanged
  EXPIRED     → NOMOS advanced off + METIS off; ESTIXE + passthrough preserved
  TAMPERED    → behavior depends on violation_behavior:
                  passthrough: all protected modules off, proxy functional
                  health_only: raises TrustViolationError (caller handles)
  INVALID     → same as TAMPERED per violation_behavior
"""

from __future__ import annotations

import logging
from aion.config import get_settings
from enum import Enum

logger = logging.getLogger("aion.trust_guard")


class TrustViolationBehavior(str, Enum):
    PASSTHROUGH = "passthrough"  # modules off, proxy 100% functional
    HEALTH_ONLY = "health_only"  # caller must block all non-health routes


class TrustViolationError(Exception):
    """Raised when violation_behavior=health_only and state is TAMPERED/INVALID."""
    def __init__(self, trust_state: str) -> None:
        super().__init__(f"AION is in {trust_state} state — only /health and /ready are available")
        self.trust_state = trust_state


# ── Module name constants (must match names registered in pipeline) ───────────
# Pre-LLM modules use their .name attribute directly.
# Post-LLM modules are registered with "{name}_post" key.

_MODULE_ESTIXE      = "estixe"
_MODULE_NOMOS       = "nomos"
_MODULE_METIS_PRE   = "metis"
_MODULE_METIS_POST  = "metis_post"

# Modules disabled in EXPIRED state (premium features)
_EXPIRED_DISABLE = (_MODULE_NOMOS, _MODULE_METIS_PRE, _MODULE_METIS_POST)

# Protected modules (off in TAMPERED/INVALID passthrough)
_PROTECTED_MODULES = (
    _MODULE_ESTIXE,
    _MODULE_NOMOS,
    _MODULE_METIS_PRE,
    _MODULE_METIS_POST,
)


class EntitlementEngine:
    """Apply entitlement constraints to the pipeline based on TrustState."""

    @staticmethod
    def apply(
        pipeline,  # aion.pipeline.Pipeline — avoid circular import
        trust_state_obj,  # aion.trust_guard.trust_state.TrustState
        behavior: TrustViolationBehavior = TrustViolationBehavior.PASSTHROUGH,
    ) -> None:
        """Apply module entitlements for the given trust state. Idempotent."""
        from aion.trust_guard.trust_state import TrustStates

        state = trust_state_obj.trust_state

        if state == TrustStates.ACTIVE:
            EntitlementEngine._restore_all(pipeline)

        elif state == TrustStates.GRACE:
            # No functional impact — only informational
            pass

        elif state == TrustStates.RESTRICTED:
            EntitlementEngine._freeze_nemos()

        elif state == TrustStates.EXPIRED:
            EntitlementEngine._freeze_nemos()
            for name in _EXPIRED_DISABLE:
                EntitlementEngine._toggle_module(pipeline, name, healthy=False,
                                                 reason="license_expired")

        elif state in {TrustStates.TAMPERED, TrustStates.INVALID}:
            if behavior == TrustViolationBehavior.HEALTH_ONLY:
                raise TrustViolationError(state)
            # passthrough: disable protected modules, proxy stays functional
            EntitlementEngine._freeze_nemos()
            for name in _PROTECTED_MODULES:
                EntitlementEngine._toggle_module(pipeline, name, healthy=False,
                                                 reason=f"trust_{state.lower()}")

    @staticmethod
    def _restore_all(pipeline) -> None:
        """Restore all Trust Guard-managed modules to healthy."""
        from aion.nemos import unfreeze_nemos_writes
        unfreeze_nemos_writes()

        all_managed = list(_PROTECTED_MODULES) + [_MODULE_METIS_POST]
        for name in all_managed:
            EntitlementEngine._toggle_module(pipeline, name, healthy=True,
                                             reason="trust_active_restored")

    @staticmethod
    def _freeze_nemos() -> None:
        """Freeze NEMOS writes (reads remain functional)."""
        try:
            from aion.nemos import freeze_nemos_writes
            freeze_nemos_writes()
        except Exception as e:
            logger.debug("trust_guard: freeze_nemos_writes failed: %s", e)

    @staticmethod
    def _toggle_module(pipeline, name: str, healthy: bool, reason: str = "") -> None:
        """Toggle a module's health. No-op if module is not registered.

        Mirrors exact logic from control_plane.py:toggle_module().
        """
        try:
            status = pipeline._module_status.get(name)
            if status is None:
                return  # module not registered or not enabled
            status.healthy = healthy
            if not healthy:
                status.consecutive_failures = get_settings().module_failure_threshold
            else:
                status.consecutive_failures = 0

            if reason:
                logger.debug(
                    "trust_guard: module %s healthy=%s reason=%s",
                    name, healthy, reason,
                )
        except Exception as e:
            logger.debug("trust_guard: _toggle_module(%s) failed: %s", name, e)
