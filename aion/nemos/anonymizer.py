"""Anonymizer — strips identifiers from signals before contributing to global learning.

Principles:
- k-anonymity: signal only enters global namespace if ≥ 5 tenants observed it
- No content: only feature vectors (intent_category, risk_tier, complexity bucket)
- LGPD compliant: no message content, no tenant identity in global signal
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("aion.nemos.anonymizer")

_K_ANON_THRESHOLD = 5  # minimum distinct tenants before global signal is accepted


def _complexity_bucket(score: float) -> str:
    if score < 0.3:
        return "low"
    if score < 0.6:
        return "medium"
    return "high"


def anonymize_signal(
    tenant: str,
    intent_category: Optional[str],
    risk_tier: str,
    complexity: float,
    decision: str,
) -> dict[str, Any]:
    """Return an anonymized feature vector (no tenant identity, no content)."""
    return {
        "intent_category": intent_category or "unknown",
        "risk_tier": risk_tier,        # "none" | "low" | "medium" | "high" | "critical"
        "complexity_bucket": _complexity_bucket(complexity),
        "decision": decision,           # "continue" | "bypass" | "block"
        "tenant_hash": hashlib.sha256(tenant.encode()).hexdigest()[:8],  # opaque bucket ID
        "timestamp": time.time(),
    }


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


async def contribute(signal: dict[str, Any]) -> None:
    """Contribute an anonymized signal to the global namespace.

    Uses a per-category tenant count to enforce k-anonymity before writing
    to global signals.
    """
    r = await _redis()
    if r is None:
        return
    try:
        category_key = f"{signal['intent_category']}:{signal['risk_tier']}:{signal['complexity_bucket']}"
        tenant_hash = signal.get("tenant_hash", "")

        # Track distinct tenant_hashes for this category
        seen_key = f"aion:global:seen:{category_key}"
        await r.sadd(seen_key, tenant_hash)
        await r.expire(seen_key, 7 * 86400)  # 7d window

        distinct_count = await r.scard(seen_key)
        if distinct_count < _K_ANON_THRESHOLD:
            return  # not enough tenants yet — don't write global signal

        # Write to global threat feed
        feed_key = f"aion:global:threats:{category_key}"
        entry = {
            "risk_tier": signal["risk_tier"],
            "decision": signal["decision"],
            "observed_at": signal["timestamp"],
            "k_anon_count": int(distinct_count),
        }
        await r.zadd(feed_key, {json.dumps(entry): signal["timestamp"]})
        # Keep last 1000 signals per category
        await r.zremrangebyrank(feed_key, 0, -1001)
        await r.expire(feed_key, 30 * 86400)

    except Exception:
        logger.debug("contribute failed (non-critical)", exc_info=True)
