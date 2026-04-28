"""AION Trust Guard — Audit event emitter.

Writes trust.* events to the existing hash-chained audit trail in
aion/middleware.py. Uses the internal _local_audit_log and _chain_tips
directly since Trust Guard events originate from background tasks (no
HTTP Request object available).

All events are also logged at INFO level under "aion.trust_guard" so
they appear in structured JSON logs visible to the customer's admin team.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("aion.trust_guard")


def emit_trust_event(event_type: str, tenant_id: str = "system", **fields: Any) -> None:
    """Emit a trust.* audit event.

    Writes to the existing middleware audit trail (hash-chained, local + Redis).
    Never raises — Trust Guard events must not crash AION.

    Event types (trust.*):
      trust.license_validated, trust.license_invalid
      trust.integrity_verified, trust.integrity_failed
      trust.state_transition
      trust.heartbeat_success, trust.heartbeat_failed
      trust.grace_period_warning
      trust.restricted_mode
      trust.module_entitlement
    """
    try:
        _write_to_audit_trail(event_type, tenant_id, fields)
        _log_event(event_type, tenant_id, fields)
    except Exception as e:
        logger.debug("trust_guard: audit emit failed for %s: %s", event_type, e)


def _write_to_audit_trail(event_type: str, tenant_id: str, fields: dict) -> None:
    """Write event to the middleware audit trail (local buffer + Redis async)."""
    import hashlib

    try:
        from aion.middleware import _local_audit_log, _chain_tips
    except ImportError:
        logger.debug("trust_guard: middleware audit trail not available")
        return

    prev_hash = _chain_tips.get(tenant_id, "0" * 64)

    entry: dict = {
        "timestamp": time.time(),
        "action": event_type,
        "path": "trust_guard",
        "method": "SYSTEM",
        "ip": "127.0.0.1",
        "tenant": tenant_id,
        "details": json.dumps(fields, default=str),
        "prev_hash": prev_hash,
        "actor_id": "trust_guard",
        "actor_role": "system",
        "auth_source": "trust_guard",
        "actor_reason": event_type,
        "actor_headers_trusted": True,
        **{f"trust_{k}": v for k, v in fields.items()},
    }

    # Compute entry hash (same logic as middleware._hash_entry)
    serialized = json.dumps(
        {k: v for k, v in entry.items() if k != "entry_hash"},
        sort_keys=True, default=str,
    )
    entry["entry_hash"] = hashlib.sha256(serialized.encode()).hexdigest()
    _chain_tips[tenant_id] = entry["entry_hash"]

    _local_audit_log.append(entry)

    # Fire-and-forget Redis write (best-effort)
    _try_redis_write(tenant_id, entry)


def _try_redis_write(tenant_id: str, entry: dict) -> None:
    """Attempt async Redis write — best-effort, never blocks."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_async_redis_write(tenant_id, entry))
    except Exception:
        pass


async def _async_redis_write(tenant_id: str, entry: dict) -> None:
    """Write audit entry to Redis asynchronously."""
    try:
        from aion.middleware import _get_redis
        r = await _get_redis()
        if r:
            redis_key = f"aion:audit:{tenant_id}"
            await r.lpush(redis_key, json.dumps(entry, default=str))
            await r.ltrim(redis_key, 0, 9999)
    except Exception:
        pass


def _log_event(event_type: str, tenant_id: str, fields: dict) -> None:
    """Log the event as structured JSON for the customer's admin team."""
    log_fields = {"event": event_type, "tenant": tenant_id, **fields}
    # Use WARNING for state changes that need attention, INFO for normal events
    _warn_events = {
        "trust.license_invalid",
        "trust.integrity_failed",
        "trust.state_transition",
        "trust.grace_period_warning",
        "trust.restricted_mode",
    }
    if event_type in _warn_events:
        logger.warning(
            '{"event":"%s",%s}',
            event_type,
            ",".join(f'"{k}":"{v}"' for k, v in log_fields.items() if k != "event"),
        )
    else:
        logger.info(
            '{"event":"%s","tenant":"%s"}',
            event_type, tenant_id,
        )
