"""Redis-backed marketplace store."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Optional

from aion.marketplace.models import MarketplacePolicy, PolicyInstallation, PolicyRating

logger = logging.getLogger("aion.marketplace.store")


async def _redis(decode: bool = True):
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(url, decode_responses=decode, socket_timeout=1.0, socket_connect_timeout=1.0)
        await r.ping()
        return r
    except Exception:
        return None


class MarketplaceStore:
    """CRUD for marketplace policies using Redis sorted sets for indexing."""

    async def publish(self, policy: MarketplacePolicy) -> MarketplacePolicy:
        if not policy.id:
            policy.id = str(uuid.uuid4())
        policy.published_at = time.time()
        policy.updated_at = time.time()
        r = await _redis()
        if r is None:
            return policy
        try:
            await r.set(f"aion:marketplace:policy:{policy.id}", policy.model_dump_json())
            # Category index: score = downloads * rating (default 0)
            score = policy.downloads * max(policy.rating, 0.1)
            await r.zadd(f"aion:marketplace:index:category:{policy.category}", {policy.id: score})
            # Global index
            await r.zadd("aion:marketplace:index:all", {policy.id: score})
        except Exception:
            logger.debug("MarketplaceStore.publish failed (non-critical)", exc_info=True)
        return policy

    async def get(self, policy_id: str) -> Optional[MarketplacePolicy]:
        r = await _redis()
        if r is None:
            return None
        try:
            raw = await r.get(f"aion:marketplace:policy:{policy_id}")
            if raw:
                return MarketplacePolicy(**json.loads(raw))
        except Exception:
            logger.debug("MarketplaceStore.get failed", exc_info=True)
        return None

    async def browse(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[MarketplacePolicy]:
        r = await _redis()
        if r is None:
            return []
        try:
            index_key = f"aion:marketplace:index:category:{category}" if category else "aion:marketplace:index:all"
            # Highest score first (most popular)
            ids = await r.zrevrange(index_key, offset, offset + limit - 1)
            policies = []
            for pid in ids:
                raw = await r.get(f"aion:marketplace:policy:{pid}")
                if raw:
                    try:
                        p = MarketplacePolicy(**json.loads(raw))
                        if tag is None or tag in p.tags:
                            policies.append(p)
                    except Exception:
                        pass
            return policies
        except Exception:
            logger.debug("MarketplaceStore.browse failed", exc_info=True)
        return []

    async def install(self, policy_id: str, tenant: str, shadow: bool = True) -> PolicyInstallation:
        installation = PolicyInstallation(policy_id=policy_id, tenant=tenant, shadow_mode=shadow)
        r = await _redis()
        if r is None:
            return installation
        try:
            await r.sadd(f"aion:marketplace:install:{tenant}", policy_id)
            install_key = f"aion:marketplace:install_record:{tenant}:{policy_id}"
            await r.set(install_key, installation.model_dump_json())
            # Increment download counter
            policy = await self.get(policy_id)
            if policy:
                policy.downloads += 1
                policy.updated_at = time.time()
                await r.set(f"aion:marketplace:policy:{policy_id}", policy.model_dump_json())
                score = policy.downloads * max(policy.rating, 0.1)
                await r.zadd(f"aion:marketplace:index:category:{policy.category}", {policy_id: score})
                await r.zadd("aion:marketplace:index:all", {policy_id: score})
        except Exception:
            logger.debug("MarketplaceStore.install failed (non-critical)", exc_info=True)
        return installation

    async def rate(self, policy_id: str, tenant: str, rating: int, comment: str = "") -> None:
        r = await _redis()
        if r is None:
            return
        try:
            pr = PolicyRating(policy_id=policy_id, tenant=tenant, rating=rating, comment=comment)
            await r.set(f"aion:marketplace:rating:{policy_id}:{tenant}", pr.model_dump_json())

            # Update rolling average on the policy
            policy = await self.get(policy_id)
            if policy:
                new_count = policy.rating_count + 1
                new_rating = (policy.rating * policy.rating_count + rating) / new_count
                policy.rating = round(new_rating, 2)
                policy.rating_count = new_count
                policy.updated_at = time.time()
                await r.set(f"aion:marketplace:policy:{policy_id}", policy.model_dump_json())
                score = policy.downloads * max(policy.rating, 0.1)
                await r.zadd(f"aion:marketplace:index:category:{policy.category}", {policy_id: score})
                await r.zadd("aion:marketplace:index:all", {policy_id: score})
        except Exception:
            logger.debug("MarketplaceStore.rate failed (non-critical)", exc_info=True)

    async def get_installations(self, tenant: str) -> list[str]:
        r = await _redis()
        if r is None:
            return []
        try:
            return list(await r.smembers(f"aion:marketplace:install:{tenant}"))
        except Exception:
            return []


_store: Optional[MarketplaceStore] = None


def get_marketplace_store() -> MarketplaceStore:
    global _store
    if _store is None:
        _store = MarketplaceStore()
    return _store
