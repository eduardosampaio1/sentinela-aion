"""AION Trust Guard — local state persistence.

TrustState is the single source of truth for the license/integrity status
cached on disk. It survives restarts and drives entitlement decisions when
the Sentinela Control Plane is unreachable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aion.trust_guard")


# ── Trust states ────────────────────────────────────────────────────────────────

class TrustStates:
    ACTIVE     = "ACTIVE"      # license valid, integrity verified
    GRACE      = "GRACE"       # license near expiry or missed heartbeat; no functional impact
    RESTRICTED = "RESTRICTED"  # license expired (within 7-day grace); NEMOS frozen
    EXPIRED    = "EXPIRED"     # license fully expired; premium features off
    TAMPERED   = "TAMPERED"    # integrity divergence detected
    INVALID    = "INVALID"     # JWT invalid (signature, tenant, claims)

    _ALL = {ACTIVE, GRACE, RESTRICTED, EXPIRED, TAMPERED, INVALID}

    # Allowed state transitions
    _TRANSITIONS: dict[str, set[str]] = {
        ACTIVE:     {GRACE, TAMPERED, INVALID},
        GRACE:      {ACTIVE, RESTRICTED, TAMPERED, INVALID},
        RESTRICTED: {ACTIVE, EXPIRED, TAMPERED, INVALID},
        EXPIRED:    {ACTIVE},    # only via restart with a new license
        TAMPERED:   set(),       # terminal — requires new deploy
        INVALID:    set(),       # terminal — requires valid license + restart
    }

    @classmethod
    def can_transition(cls, from_state: str, to_state: str) -> bool:
        return to_state in cls._TRANSITIONS.get(from_state, set())


# ── Integrity status ─────────────────────────────────────────────────────────

class IntegrityStatus:
    VERIFIED   = "VERIFIED"
    TAMPERED   = "TAMPERED"
    UNVERIFIED = "UNVERIFIED"


# ── TrustState dataclass ──────────────────────────────────────────────────────

@dataclass
class TrustState:
    trust_state: str = TrustStates.ACTIVE
    license_id: str = ""
    tenant_id: str = ""
    build_id: str = ""
    aion_version: str = ""
    integrity_status: str = IntegrityStatus.UNVERIFIED
    files_diverged: list = field(default_factory=list)
    entitlement_expires_at: float = 0.0
    last_heartbeat_at: float = 0.0
    last_heartbeat_success: bool = False
    restricted_features: list = field(default_factory=list)
    state_reason: str = ""
    grace_hours_remaining: Optional[float] = None
    heartbeat_required: bool = False
    heartbeat_url: str = ""
    persisted_at: float = 0.0

    def is_operational(self) -> bool:
        """True when AION modules should function normally."""
        return self.trust_state == TrustStates.ACTIVE

    def is_degraded(self) -> bool:
        """True when some modules must be disabled."""
        return self.trust_state in {
            TrustStates.RESTRICTED,
            TrustStates.EXPIRED,
            TrustStates.TAMPERED,
            TrustStates.INVALID,
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrustState":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ── File persistence ──────────────────────────────────────────────────────────

def _state_file() -> Path:
    """Return path to trust_state.json. Follows same pattern as middleware._overrides_file()."""
    base = Path(os.environ.get("AION_RUNTIME_DIR", ".runtime"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "trust_state.json"


def load_trust_state() -> TrustState:
    """Load TrustState from disk. Returns default TrustState on any error — never raises."""
    try:
        path = _state_file()
        if not path.exists():
            return TrustState()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TrustState.from_dict(data)
    except Exception as e:
        logger.debug("trust_state: load failed (returning default): %s", e)
        return TrustState()


def save_trust_state(state: TrustState) -> None:
    """Persist TrustState atomically (temp file + rename). Errors are silently logged."""
    try:
        state.persisted_at = time.time()
        path = _state_file()
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception as e:
        logger.debug("trust_state: save failed: %s", e)
