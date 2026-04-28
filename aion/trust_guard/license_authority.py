"""AION Trust Guard — License Authority.

Extracts Trust Guard-relevant claims from the validated license JWT.
All fields are optional in the JWT — absence returns safe defaults,
which silently disables heartbeat/entitlement features for that tenant.
"""

from __future__ import annotations

import time
from typing import Optional

from aion.license import LicenseState, get_license
from aion.trust_guard.trust_state import TrustState, TrustStates


def get_license_claims() -> dict:
    """Return Trust Guard claims from the current license.

    Returns a dict with:
      license_id, tenant_id, tier, expires_at, env,
      heartbeat_required (bool, default False),
      heartbeat_url (str, default ""),
      min_aion_version (str, default ""),
      features (list[str], default [])
    """
    lic = get_license()
    raw = _get_raw_claims()

    return {
        "license_id":          raw.get("license_id", raw.get("jti", "")),
        "tenant_id":           lic.tenant,
        "tier":                lic.tier,
        "expires_at":          lic.expires_at,
        "env":                 lic.env,
        "features":            lic.features,
        "heartbeat_required":  bool(raw.get("heartbeat_required", False)),
        "heartbeat_url":       str(raw.get("heartbeat_url", "")),
        "min_aion_version":    str(raw.get("min_aion_version", "")),
    }


def determine_license_state(claims: dict) -> tuple[str, str]:
    """Determine the TrustState and reason from the current license state.

    Returns (trust_state, reason).
    """
    lic = get_license()

    if lic.state == LicenseState.INVALID:
        return TrustStates.INVALID, "license_invalid"

    if lic.state == LicenseState.EXPIRED:
        return TrustStates.EXPIRED, "license_expired"

    if lic.state == LicenseState.GRACE:
        return TrustStates.GRACE, "license_grace_period"

    # ACTIVE — check if approaching expiry (< 7 days)
    now = time.time()
    expires_at = claims.get("expires_at", 0.0)
    seven_days = 7 * 24 * 3600
    if expires_at and (expires_at - now) < seven_days:
        return TrustStates.GRACE, "license_expiring_soon"

    return TrustStates.ACTIVE, "active_license"


def build_initial_trust_state(claims: dict, build_id: str, aion_version: str) -> TrustState:
    """Build a TrustState from license claims (before integrity check).

    Integrity status is left as UNVERIFIED — caller sets it after verify_manifest().
    """
    from aion.trust_guard.trust_state import TrustState, TrustStates, IntegrityStatus
    import time

    trust_state, reason = determine_license_state(claims)

    state = TrustState(
        trust_state=trust_state,
        license_id=claims.get("license_id", ""),
        tenant_id=claims.get("tenant_id", ""),
        build_id=build_id,
        aion_version=aion_version,
        integrity_status=IntegrityStatus.UNVERIFIED,
        entitlement_expires_at=claims.get("expires_at", 0.0),
        heartbeat_required=claims.get("heartbeat_required", False),
        heartbeat_url=claims.get("heartbeat_url", ""),
        state_reason=reason,
        persisted_at=time.time(),
    )

    # Compute grace_hours_remaining for GRACE state
    if trust_state == TrustStates.GRACE:
        now = time.time()
        expires_at = claims.get("expires_at", 0.0)
        if expires_at:
            hours = (expires_at - now) / 3600
            state.grace_hours_remaining = max(0.0, round(hours, 1))

    return state


def _get_raw_claims() -> dict:
    """Return the raw JWT claims dict. Imported lazily to avoid circular import."""
    try:
        from aion.license import _raw_claims as raw  # type: ignore[attr-defined]
        return raw if isinstance(raw, dict) else {}
    except (ImportError, AttributeError):
        return {}
