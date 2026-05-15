"""KairosStore — Redis backend (ephemeral hot store).

WARNING: Redis-only mode means data is lost on restart.
Use storage_mode=postgres or storage_mode=sqlite for production/enterprise.
This backend is suitable for:
  - integration tests
  - rapid prototyping
  - hot-path cache (used as secondary layer alongside postgres/sqlite)

Follows the same async + local-fallback pattern as aion/nemos/store.py.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from aion.kairos.models import (
    LifecycleEvent,
    PolicyCandidate,
    PolicyCandidateStatus,
    ShadowRun,
)

logger = logging.getLogger("aion.kairos.store.redis")

_TTL_CANDIDATES = 90 * 86_400   # 90 days
_TTL_EVENTS = 365 * 86_400       # 1 year
_TTL_SHADOW = 90 * 86_400        # 90 days


def _ckey(tenant_id: str, candidate_id: str) -> str:
    return f"aion:kairos:{tenant_id}:candidates:{candidate_id}"


def _ekey(candidate_id: str, event_id: str) -> str:
    return f"aion:kairos:events:{candidate_id}:{event_id}"


def _elist_key(candidate_id: str) -> str:
    return f"aion:kairos:events:{candidate_id}:index"


def _skey(run_id: str) -> str:
    return f"aion:kairos:shadow:{run_id}"


class RedisKairosStore:
    """Redis-backed KAIROS store. Ephemeral — data survives only while Redis is alive."""

    def __init__(self) -> None:
        self._redis = None

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            from aion.middleware import _redis_client, _redis_available  # noqa: PLC0415
            if _redis_available and _redis_client:
                self._redis = _redis_client
                return self._redis
        except Exception:
            pass
        return None

    async def save_candidate(self, candidate: PolicyCandidate) -> None:
        redis = await self._get_redis()
        if not redis:
            return
        try:
            key = _ckey(candidate.tenant_id, candidate.id)
            await redis.set(key, candidate.model_dump_json(), ex=_TTL_CANDIDATES)
        except Exception:
            logger.debug("Redis: failed to save candidate %s", candidate.id, exc_info=True)

    async def get_candidate(
        self, tenant_id: str, candidate_id: str
    ) -> Optional[PolicyCandidate]:
        redis = await self._get_redis()
        if not redis:
            return None
        try:
            raw = await redis.get(_ckey(tenant_id, candidate_id))
            if raw:
                return PolicyCandidate.model_validate_json(raw)
        except Exception:
            logger.debug("Redis: failed to get candidate %s", candidate_id, exc_info=True)
        return None

    async def list_candidates(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        policy_type: Optional[str] = None,
    ) -> list[PolicyCandidate]:
        redis = await self._get_redis()
        if not redis:
            return []
        results = []
        try:
            pattern = f"aion:kairos:{tenant_id}:candidates:*"
            async for key in redis.scan_iter(match=pattern):
                raw = await redis.get(key)
                if not raw:
                    continue
                try:
                    c = PolicyCandidate.model_validate_json(raw)
                    if status and c.status.value != status:
                        continue
                    if policy_type and c.type != policy_type:
                        continue
                    results.append(c)
                except Exception:
                    pass
        except Exception:
            logger.debug("Redis: failed to list candidates for %s", tenant_id, exc_info=True)
        return sorted(results, key=lambda c: c.created_at, reverse=True)

    async def save_lifecycle_event(self, event: LifecycleEvent) -> None:
        redis = await self._get_redis()
        if not redis:
            return
        try:
            await redis.set(_ekey(event.candidate_id, event.id), event.model_dump_json(), ex=_TTL_EVENTS)
            await redis.rpush(_elist_key(event.candidate_id), event.id)
            await redis.expire(_elist_key(event.candidate_id), _TTL_EVENTS)
        except Exception:
            logger.debug("Redis: failed to save lifecycle event %s", event.id, exc_info=True)

    async def get_lifecycle_events(self, candidate_id: str) -> list[LifecycleEvent]:
        redis = await self._get_redis()
        if not redis:
            return []
        results = []
        try:
            ids = await redis.lrange(_elist_key(candidate_id), 0, -1)
            for event_id in ids:
                raw = await redis.get(_ekey(candidate_id, event_id))
                if raw:
                    try:
                        results.append(LifecycleEvent.model_validate_json(raw))
                    except Exception:
                        pass
        except Exception:
            logger.debug("Redis: failed to get lifecycle events for %s", candidate_id, exc_info=True)
        return sorted(results, key=lambda e: e.created_at)

    async def save_shadow_run(self, run: ShadowRun) -> None:
        redis = await self._get_redis()
        if not redis:
            return
        try:
            await redis.set(_skey(run.id), run.model_dump_json(), ex=_TTL_SHADOW)
        except Exception:
            logger.debug("Redis: failed to save shadow run %s", run.id, exc_info=True)

    async def get_shadow_run(self, run_id: str) -> Optional[ShadowRun]:
        redis = await self._get_redis()
        if not redis:
            return None
        try:
            raw = await redis.get(_skey(run_id))
            if raw:
                return ShadowRun.model_validate_json(raw)
        except Exception:
            logger.debug("Redis: failed to get shadow run %s", run_id, exc_info=True)
        return None

    # Lua script for atomic counter increment — prevents lost updates under concurrency.
    # ARGV[1]=observations, ARGV[2]=matched, ARGV[3]=fallback, ARGV[4]=canonical_ttl_seconds
    # PTTL semantics: >0=ms remaining, -1=no TTL, -2=key missing (expired between GET and PTTL).
    _INCREMENT_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then return nil end
local ok, data = pcall(cjson.decode, raw)
if not ok then return nil end
data['observations_count'] = (data['observations_count'] or 0) + (tonumber(ARGV[1]) or 0)
data['matched_count']      = (data['matched_count']      or 0) + (tonumber(ARGV[2]) or 0)
data['fallback_count']     = (data['fallback_count']     or 0) + (tonumber(ARGV[3]) or 0)
local ttl = redis.call('PTTL', KEYS[1])
if ttl == -2 then return nil end
if ttl > 0 then
    redis.call('SET', KEYS[1], cjson.encode(data), 'PX', ttl)
else
    redis.call('SET', KEYS[1], cjson.encode(data), 'EX', tonumber(ARGV[4]))
end
return 1
"""

    async def increment_shadow_counters(
        self,
        run_id: str,
        matched: int = 0,
        fallback: int = 0,
        observations: int = 1,
    ) -> None:
        redis = await self._get_redis()
        if not redis:
            return
        key = _skey(run_id)
        try:
            await redis.eval(
                self._INCREMENT_LUA, 1, key,
                observations, matched, fallback, _TTL_SHADOW,
            )
        except Exception:
            logger.warning(
                "Redis: atomic increment failed for run %s, falling back to non-atomic",
                run_id, exc_info=True,
            )
            # Non-atomic fallback — acceptable for ephemeral Redis under low concurrency
            run = await self.get_shadow_run(run_id)
            if not run:
                return
            run.observations_count += observations
            run.matched_count += matched
            run.fallback_count += fallback
            await self.save_shadow_run(run)

    async def list_shadow_running_candidates(
        self, tenant_id: Optional[str] = None
    ) -> list[PolicyCandidate]:
        if tenant_id:
            return await self.list_candidates(tenant_id, status=PolicyCandidateStatus.SHADOW_RUNNING.value)
        # Cross-tenant scan (sweep use case)
        redis = await self._get_redis()
        if not redis:
            return []
        results = []
        try:
            pattern = "aion:kairos:*:candidates:*"
            async for key in redis.scan_iter(match=pattern):
                raw = await redis.get(key)
                if not raw:
                    continue
                try:
                    c = PolicyCandidate.model_validate_json(raw)
                    if c.status == PolicyCandidateStatus.SHADOW_RUNNING:
                        results.append(c)
                except Exception:
                    pass
        except Exception:
            logger.debug("Redis: failed to list shadow_running candidates", exc_info=True)
        return results
