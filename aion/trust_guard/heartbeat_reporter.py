"""AION Trust Guard — Heartbeat Reporter (Fase 2).

Sends a periodic operational signal to the Sentinela Control Plane.
The server can respond with updated entitlement (trust_state, restricted_features,
entitlement_expires_at), which the client applies immediately.

Security note:
  The heartbeat payload includes a files_hash of critical module files as an
  operational integrity signal. This is NOT a cryptographic proof — a sophisticated
  attacker with root access to the container could forge the hash. The strong
  tamper protection is the Ed25519-signed integrity manifest verified locally at
  boot (integrity_manifest.py). The heartbeat is a commercial/operational channel.

Grace period logic on network failure:
  - heartbeat_required=False  → silent no-op; state unchanged
  - heartbeat_required=True   → check last_heartbeat_at against grace_hours
      - within grace  → emit warning, stay in current state
      - grace expired → transition current state to GRACE (not RESTRICTED;
                        that only happens on license expiry, not heartbeat absence)

mTLS (Fase 3):
  Mutual TLS is activated when any of these env vars are set:
    AION_TRUST_GUARD_CLIENT_CERT — PEM path of the client certificate
    AION_TRUST_GUARD_CLIENT_KEY  — PEM path of the client private key
    AION_TRUST_GUARD_CA_CERT     — PEM path of the CA bundle to verify the server
  All three must be set together for mTLS; CA_CERT alone enables one-way TLS pinning.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger("aion.trust_guard")

# Timeout for each heartbeat POST (seconds)
_HEARTBEAT_TIMEOUT = 10.0


class HeartbeatReporter:
    """Send periodic heartbeat to Sentinela Control Plane and apply entitlement."""

    @staticmethod
    async def report(
        state: "TrustState",
        heartbeat_url: str,
        grace_hours: int = 48,
    ) -> "TrustState":
        """POST heartbeat; return (potentially updated) TrustState.

        On success: update state from server response and persist.
        On any network/server error: apply grace-period logic and return
        the current state (possibly transitioned to GRACE).

        Never raises — all exceptions are caught internally.
        """
        from aion.trust_guard.trust_state import TrustState, TrustStates, save_trust_state
        from aion.trust_guard.audit_emitter import emit_trust_event

        payload = _build_payload(state)

        try:
            response_data = await _post_heartbeat(heartbeat_url, payload)
            updated = _apply_server_response(state, response_data)
            save_trust_state(updated)
            emit_trust_event(
                "trust.heartbeat_success",
                tenant_id=updated.tenant_id or "system",
                trust_state=updated.trust_state,
                entitlement_expires_at=str(updated.entitlement_expires_at),
            )
            logger.debug(
                "trust_guard: heartbeat success — trust_state=%s", updated.trust_state
            )
            return updated

        except Exception as e:
            logger.debug("trust_guard: heartbeat failed: %s", e)
            degraded = _handle_failure(state, grace_hours)
            save_trust_state(degraded)
            grace_remaining = _grace_remaining_hours(state)
            emit_trust_event(
                "trust.heartbeat_failed",
                tenant_id=state.tenant_id or "system",
                cached_state=state.trust_state,
                grace_remaining_hours=str(round(grace_remaining, 1))
                if grace_remaining is not None
                else "N/A",
                error=str(e)[:200],
            )
            return degraded


def _build_payload(state: "TrustState") -> dict:
    """Build the heartbeat POST payload."""
    from aion.trust_guard.integrity_manifest import compute_files_hash

    try:
        files_hash = compute_files_hash()
    except Exception:
        files_hash = ""

    return {
        "tenant_id": state.tenant_id,
        "build_id": state.build_id,
        "aion_version": state.aion_version,
        "files_hash": files_hash,
        "timestamp": time.time(),
    }


async def _post_heartbeat(url: str, payload: dict) -> dict:
    """POST payload to heartbeat_url. Returns parsed JSON response.

    Raises on non-2xx, timeout, or network error.
    Activates mTLS automatically when AION_TRUST_GUARD_CLIENT_CERT/KEY/CA_CERT are set.
    """
    import httpx

    ssl_context = _build_ssl_context()
    async with httpx.AsyncClient(timeout=_HEARTBEAT_TIMEOUT, verify=ssl_context) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "User-Agent": "aion-trust-guard/1.0"},
        )
        resp.raise_for_status()
        return resp.json()


def _build_ssl_context():
    """Build an SSL context from env-configured cert paths.

    Returns True (httpx default) when no mTLS env vars are set.
    Returns an ssl.SSLContext with client cert + optional CA pinning when configured.
    """
    client_cert = os.environ.get("AION_TRUST_GUARD_CLIENT_CERT", "").strip()
    client_key  = os.environ.get("AION_TRUST_GUARD_CLIENT_KEY", "").strip()
    ca_cert     = os.environ.get("AION_TRUST_GUARD_CA_CERT", "").strip()

    if not any([client_cert, client_key, ca_cert]):
        return True  # default httpx SSL (system CAs)

    import ssl

    ctx = ssl.create_default_context(cafile=ca_cert if ca_cert else None)

    if client_cert and client_key:
        ctx.load_cert_chain(certfile=client_cert, keyfile=client_key)
        logger.debug(
            "trust_guard: mTLS active — cert=%s ca=%s",
            client_cert, ca_cert or "system",
        )
    elif client_cert or client_key:
        logger.warning(
            "trust_guard: mTLS misconfigured — both CLIENT_CERT and CLIENT_KEY required"
        )

    return ctx


def _apply_server_response(state: "TrustState", data: dict) -> "TrustState":
    """Merge server-provided entitlement into the existing TrustState.

    The server may return any subset of: trust_state, entitlement_expires_at,
    restricted_features. Unknown fields are silently ignored.
    Only valid TrustStates are accepted; anything else keeps the current state.
    """
    from aion.trust_guard.trust_state import TrustStates
    import dataclasses

    updated = dataclasses.replace(state)
    updated.last_heartbeat_at = time.time()
    updated.last_heartbeat_success = True

    server_state = data.get("trust_state", "")
    if server_state and server_state in TrustStates._ALL:
        updated.trust_state = server_state

    if "entitlement_expires_at" in data:
        try:
            updated.entitlement_expires_at = float(data["entitlement_expires_at"])
        except (TypeError, ValueError):
            pass

    if "restricted_features" in data and isinstance(data["restricted_features"], list):
        updated.restricted_features = data["restricted_features"]

    # Recompute grace_hours_remaining if server returned an expiry
    if updated.entitlement_expires_at:
        remaining = (updated.entitlement_expires_at - time.time()) / 3600
        if remaining > 0 and updated.trust_state == TrustStates.GRACE:
            updated.grace_hours_remaining = round(remaining, 1)
        else:
            updated.grace_hours_remaining = None

    return updated


def _handle_failure(state: "TrustState", grace_hours: int) -> "TrustState":
    """Apply grace-period logic when the heartbeat server is unreachable.

    - heartbeat_required=False → silent no-op (state unchanged)
    - heartbeat_required=True  → check how long since last successful heartbeat
        - within grace_hours   → keep state, log warning
        - past grace_hours     → transition to GRACE (admin visibility, no module impact)
    """
    import dataclasses
    from aion.trust_guard.trust_state import TrustStates

    if not state.heartbeat_required:
        return state  # no change; heartbeat is optional

    grace_remaining = _grace_remaining_hours(state)

    if grace_remaining is None or grace_remaining > 0:
        # Within grace window — no state change, just warn
        if grace_remaining is not None:
            logger.warning(
                "trust_guard: heartbeat unreachable, heartbeat_required=true; "
                "%.1fh of grace remaining before GRACE state",
                grace_remaining,
            )
        return state

    # Grace window exhausted — transition to GRACE (informational, no module impact)
    if state.trust_state == TrustStates.ACTIVE:
        updated = dataclasses.replace(state)
        updated.trust_state = TrustStates.GRACE
        updated.state_reason = "heartbeat_grace_expired"
        updated.grace_hours_remaining = 0.0
        logger.warning(
            "trust_guard: heartbeat grace period exhausted — transitioning to GRACE"
        )
        return updated

    return state


def _grace_remaining_hours(state: "TrustState") -> Optional[float]:
    """Return hours remaining in grace period, or None if never attempted/configured."""
    if not state.last_heartbeat_at:
        # Heartbeat has never succeeded — use startup time as reference
        return None  # treat as within grace (benefit of the doubt on first boot)

    from aion.config import get_trust_guard_settings
    try:
        grace_hours = get_trust_guard_settings().grace_hours
    except Exception:
        grace_hours = 48

    elapsed_hours = (time.time() - state.last_heartbeat_at) / 3600
    return max(0.0, grace_hours - elapsed_hours)
