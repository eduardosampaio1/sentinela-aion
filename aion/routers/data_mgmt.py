"""Data management router: /v1/audit, /v1/data/{tenant}, /v1/admin/rotate-keys."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, HTTPException

from aion.config import get_settings
from aion.middleware import audit, get_audit_log

logger = logging.getLogger("aion")

router = APIRouter()


@router.get("/v1/audit", tags=["Data Management"])
async def audit_log_endpoint(request: Request, limit: int = 100):
    """Get audit trail for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return await get_audit_log(limit, tenant)


@router.delete("/v1/data/{tenant}", tags=["Data Management"])
async def delete_tenant_data(tenant: str):
    """Delete all data for a tenant (LGPD compliance)."""
    from aion.metis.behavior import BehaviorDial

    dial = BehaviorDial()
    await dial.delete(tenant)

    from aion.shared.telemetry import _event_buffer
    original_len = len(_event_buffer)
    for _ in range(original_len):
        if _event_buffer:
            event = _event_buffer.popleft()
            if event.get("tenant") != tenant:
                _event_buffer.append(event)

    try:
        from aion.cache import get_cache
        get_cache().delete_tenant(tenant)
    except Exception:
        logger.debug("Cache delete failed for tenant %s", tenant)

    try:
        from aion.estixe.suggestions import get_suggestion_engine
        get_suggestion_engine().delete_tenant(tenant)
    except Exception:
        logger.debug("Suggestion engine delete failed for tenant %s", tenant)

    nemos_deleted = 0
    try:
        from aion.nemos import get_nemos
        nemos_deleted = await get_nemos().delete_tenant_data(tenant)
    except Exception:
        logger.debug("NEMOS delete failed for tenant %s", tenant)

    return {"tenant": tenant, "status": "deleted", "nemos_keys_deleted": nemos_deleted}


@router.post("/v1/admin/rotate-keys", tags=["Control Plane"])
async def rotate_admin_keys(request: Request):
    """Rotate HMAC signing key without service downtime."""
    import time as _time
    import os
    body = await request.json()
    new_secret = body.get("new_secret", "")
    reason = body.get("reason", "manual rotation")
    if len(new_secret) < 32:
        raise HTTPException(status_code=422, detail="new_secret must be at least 32 characters")

    os.environ["AION_SESSION_AUDIT_SECRET"] = new_secret

    import aion.config as _cfg
    _cfg._settings = None

    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    await audit("admin:rotate-keys", request, tenant, f"reason={reason}")

    return {
        "status": "rotated",
        "reason": reason,
        "rotated_at": _time.time(),
        "note": "Update AION_SESSION_AUDIT_SECRET env var and restart replicas to persist.",
    }
