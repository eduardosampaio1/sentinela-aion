"""Global feed router: /v1/global/threat-feed/{tenant_id}."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from aion.config import get_settings

logger = logging.getLogger("aion")

router = APIRouter()


@router.get("/v1/global/threat-feed/{tenant_id}", tags=["Intelligence"])
async def global_threat_feed(tenant_id: str, category: str = None, limit: int = 50):
    """Return k-anonymized global threat signals for opt-in tenants."""
    settings = get_settings()
    if not settings.contribute_global_learning:
        return {
            "tenant": tenant_id,
            "enabled": False,
            "note": "Set AION_CONTRIBUTE_GLOBAL_LEARNING=true to access global threat feed.",
            "signals": [],
        }
    try:
        from aion.nemos.global_model import get_global_reader
        signals = await get_global_reader().get_threat_feed(category_filter=category, limit=limit)
        return {"tenant": tenant_id, "enabled": True, "signals": signals, "count": len(signals)}
    except Exception as exc:
        logger.error("Global threat feed failed: %s", exc)
        return {"tenant": tenant_id, "enabled": True, "signals": [], "error": str(exc)}
