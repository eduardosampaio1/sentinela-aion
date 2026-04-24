"""Global model — contributor and reader for cross-tenant aggregated signals."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("aion.nemos.global_model")


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


class GlobalSignalContributor:
    """Records anonymized signals from opt-in tenants."""

    async def record(
        self,
        tenant: str,
        intent_category: Optional[str],
        risk_tier: str,
        complexity: float,
        decision: str,
    ) -> None:
        from aion.nemos.anonymizer import anonymize_signal, contribute
        signal = anonymize_signal(tenant, intent_category, risk_tier, complexity, decision)
        await contribute(signal)


class GlobalModelReader:
    """Reads aggregated global signals for opt-in tenants."""

    async def get_threat_feed(self, category_filter: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Return k-anon verified threat signals from the global feed."""
        r = await _redis()
        if r is None:
            return []
        results: list[dict[str, Any]] = []
        try:
            if category_filter:
                pattern = f"aion:global:threats:{category_filter}:*"
            else:
                pattern = "aion:global:threats:*"
            cursor = 0
            keys_seen: list[str] = []
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=100)
                keys_seen.extend(keys)
                if cursor == 0:
                    break

            for key in keys_seen[:20]:  # cap at 20 categories
                category_key = key.replace("aion:global:threats:", "")
                entries = await r.zrevrange(key, 0, limit - 1, withscores=True)
                for raw, score in entries:
                    try:
                        entry = json.loads(raw)
                        entry["category_key"] = category_key
                        entry["observed_at_ts"] = score
                        results.append(entry)
                    except Exception:
                        pass
                if len(results) >= limit:
                    break

        except Exception:
            logger.debug("GlobalModelReader.get_threat_feed failed (non-critical)", exc_info=True)
        return results[:limit]


_contributor: Optional[GlobalSignalContributor] = None
_reader: Optional[GlobalModelReader] = None


def get_global_contributor() -> GlobalSignalContributor:
    global _contributor
    if _contributor is None:
        _contributor = GlobalSignalContributor()
    return _contributor


def get_global_reader() -> GlobalModelReader:
    global _reader
    if _reader is None:
        _reader = GlobalModelReader()
    return _reader
