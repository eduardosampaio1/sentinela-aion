"""NEMOS store — Redis-backed persistence with local fallback.

Follows the exact same pattern as BehaviorDial (aion/metis/behavior.py)
and middleware.py: async Redis with transparent local fallback.

All writes are fire-and-forget (errors logged, never raised).
All reads fall back to local store if Redis is unavailable.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from typing import Any, Optional

from aion.config import get_settings

logger = logging.getLogger("aion.nemos.store")

# ── Redis client (shared, lazy init) ──
_redis_client = None
_redis_available = False


async def _get_redis():
    """Get or create async Redis client. Returns None if unavailable."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None

    settings = get_settings()
    if not settings.redis_url:
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=2.0,
        )
        await _redis_client.ping()
        _redis_available = True
        logger.info("NEMOS store: Redis connected")
        return _redis_client
    except Exception:
        logger.warning("NEMOS store: Redis unavailable, using local fallback")
        _redis_available = False
        return None


class BoundedDict(OrderedDict):
    """OrderedDict with max size — evicts oldest on overflow."""

    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._maxlen = maxlen

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self._maxlen:
            self.popitem(last=False)


class NemosStore:
    """Low-level key-value store backed by Redis hashes with local fallback."""

    def __init__(self, local_maxlen: int = 1000) -> None:
        self._local: BoundedDict = BoundedDict(maxlen=local_maxlen)

    async def hset(self, key: str, field: str, value: str, ttl_seconds: int | None = None) -> None:
        """Set a hash field. Fire-and-forget on Redis, always writes local."""
        # Always update local
        if key not in self._local:
            self._local[key] = {}
        self._local[key][field] = value

        redis = await _get_redis()
        if redis:
            try:
                await redis.hset(key, field, value)
                if ttl_seconds:
                    await redis.expire(key, ttl_seconds)
            except Exception:
                logger.debug("NEMOS hset failed for %s, local fallback active", key)

    async def hset_dict(self, key: str, data: dict[str, str], ttl_seconds: int | None = None) -> None:
        """Set multiple hash fields at once."""
        if key not in self._local:
            self._local[key] = {}
        self._local[key].update(data)

        redis = await _get_redis()
        if redis:
            try:
                pipe = redis.pipeline()
                pipe.hset(key, mapping=data)
                if ttl_seconds:
                    pipe.expire(key, ttl_seconds)
                await pipe.execute()
            except Exception:
                logger.debug("NEMOS hset_dict failed for %s, local fallback active", key)

    async def hgetall(self, key: str) -> dict[str, str]:
        """Get all fields of a hash. Redis first, local fallback."""
        redis = await _get_redis()
        if redis:
            try:
                data = await redis.hgetall(key)
                if data:
                    # Update local cache
                    self._local[key] = dict(data)
                    return data
            except Exception:
                logger.debug("NEMOS hgetall failed for %s, local fallback", key)

        return dict(self._local.get(key, {}))

    async def hget(self, key: str, field: str) -> str | None:
        """Get a single hash field."""
        redis = await _get_redis()
        if redis:
            try:
                val = await redis.hget(key, field)
                if val is not None:
                    return val
            except Exception:
                pass

        local = self._local.get(key, {})
        return local.get(field)

    async def hincrby(self, key: str, field: str, amount: int = 1, ttl_seconds: int | None = None) -> int:
        """Increment a hash field."""
        # Local
        if key not in self._local:
            self._local[key] = {}
        current = int(self._local[key].get(field, 0))
        new_val = current + amount
        self._local[key][field] = str(new_val)

        redis = await _get_redis()
        if redis:
            try:
                result = await redis.hincrby(key, field, amount)
                if ttl_seconds:
                    await redis.expire(key, ttl_seconds)
                return result
            except Exception:
                pass

        return new_val

    async def hincrbyfloat(self, key: str, field: str, amount: float, ttl_seconds: int | None = None) -> float:
        """Increment a hash field by float."""
        if key not in self._local:
            self._local[key] = {}
        current = float(self._local[key].get(field, 0))
        new_val = current + amount
        self._local[key][field] = str(new_val)

        redis = await _get_redis()
        if redis:
            try:
                result = await redis.hincrbyfloat(key, field, amount)
                if ttl_seconds:
                    await redis.expire(key, ttl_seconds)
                return result
            except Exception:
                pass

        return new_val

    async def set_json(self, key: str, data: Any, ttl_seconds: int | None = None) -> None:
        """Store a JSON-serializable object."""
        serialized = json.dumps(data)
        self._local[key] = serialized

        redis = await _get_redis()
        if redis:
            try:
                if ttl_seconds:
                    await redis.setex(key, ttl_seconds, serialized)
                else:
                    await redis.set(key, serialized)
            except Exception:
                logger.debug("NEMOS set_json failed for %s", key)

    async def get_json(self, key: str) -> Any | None:
        """Retrieve a JSON object."""
        redis = await _get_redis()
        if redis:
            try:
                val = await redis.get(key)
                if val:
                    parsed = json.loads(val)
                    self._local[key] = val
                    return parsed
            except Exception:
                pass

        local = self._local.get(key)
        if local and isinstance(local, str):
            try:
                return json.loads(local)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern. Returns count deleted."""
        deleted = 0

        # Local
        to_remove = [k for k in self._local if _match_pattern(k, pattern)]
        for k in to_remove:
            del self._local[k]
            deleted += 1

        # Redis
        redis = await _get_redis()
        if redis:
            try:
                cursor = "0"
                while cursor != 0:
                    cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
                    if keys:
                        await redis.delete(*keys)
                        deleted += len(keys)
            except Exception:
                logger.debug("NEMOS delete_pattern failed for %s", pattern)

        return deleted

    async def keys_by_prefix(self, prefix: str) -> list[str]:
        """List keys with a prefix. Local fallback only."""
        redis = await _get_redis()
        if redis:
            try:
                keys = []
                cursor = "0"
                while cursor != 0:
                    cursor, batch = await redis.scan(cursor=cursor, match=f"{prefix}*", count=100)
                    keys.extend(batch)
                return keys
            except Exception:
                pass

        return [k for k in self._local if k.startswith(prefix)]


def _match_pattern(key: str, pattern: str) -> bool:
    """Simple glob match for local keys (supports * at end)."""
    if pattern.endswith("*"):
        return key.startswith(pattern[:-1])
    return key == pattern
