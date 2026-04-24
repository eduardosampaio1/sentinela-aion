"""Report scheduler — Redis-backed schedule storage for automated monthly reports."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger("aion.reports.scheduler")


class ReportSchedule(BaseModel):
    tenant: str
    frequency: str = "monthly"  # "monthly" | "weekly"
    recipients: list[str] = []  # email addresses (delivery TBD)
    format: str = "pdf"         # "pdf" | "json"
    created_at: float = 0.0
    last_generated_at: Optional[float] = None


async def _redis():
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0)
        await r.ping()
        return r
    except Exception:
        return None


async def save_schedule(schedule: ReportSchedule) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        key = f"aion:report_schedule:{schedule.tenant}"
        await r.set(key, schedule.model_dump_json())
    except Exception:
        logger.debug("save_schedule failed (non-critical)", exc_info=True)


async def get_schedule(tenant: str) -> Optional[ReportSchedule]:
    r = await _redis()
    if r is None:
        return None
    try:
        key = f"aion:report_schedule:{tenant}"
        raw = await r.get(key)
        if raw:
            return ReportSchedule(**json.loads(raw))
    except Exception:
        logger.debug("get_schedule failed (non-critical)", exc_info=True)
    return None


async def delete_schedule(tenant: str) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        await r.delete(f"aion:report_schedule:{tenant}")
    except Exception:
        pass


async def get_cached_report(tenant: str, period: str) -> Optional[bytes]:
    """Return cached PDF bytes for a period key (YYYY-MM), or None."""
    r = await _redis()
    if r is None:
        return None
    try:
        import redis.asyncio as aioredis
        # Use binary client for PDF bytes
        url = os.environ.get("REDIS_URL", "")
        rb = aioredis.from_url(url, decode_responses=False, socket_timeout=1.0, socket_connect_timeout=1.0)
        raw = await rb.get(f"aion:report:{tenant}:{period}")
        await rb.aclose()
        return raw
    except Exception:
        return None


async def cache_report(tenant: str, period: str, pdf_bytes: bytes) -> None:
    """Cache PDF bytes for 35 days."""
    try:
        import redis.asyncio as aioredis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return
        rb = aioredis.from_url(url, decode_responses=False, socket_timeout=1.0, socket_connect_timeout=1.0)
        await rb.setex(f"aion:report:{tenant}:{period}", 35 * 86400, pdf_bytes)
        await rb.aclose()
    except Exception:
        logger.debug("cache_report failed (non-critical)", exc_info=True)
