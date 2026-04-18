"""Semantic Cache — cache LLM responses by meaning, not exact text.

"Qual a capital do Brasil?" and "Me diz a capital brasileira" hit the same cache entry.

Design principles:
- Per-tenant isolation (one tenant never sees another's cache)
- Multi-signal invalidation (followup + similarity drop + TTL — no single signal)
- Fail-open: if cache breaks, pipeline continues normally (miss = call LLM)
- TTL varies by intent type (factual=long, creative=short)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from aion.config import get_cache_settings
from aion.shared.embeddings import get_embedding_model
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Decision,
    PipelineContext,
)
from aion.shared.tokens import extract_user_message
from aion.shared.vector_store import TenantVectorStore, get_vector_store_manager

logger = logging.getLogger("aion.cache")


@dataclass
class CacheStats:
    """Cache performance metrics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0
    entries_by_tenant: dict[str, int] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def total_entries(self) -> int:
        return sum(self.entries_by_tenant.values())


class SemanticCache:
    """Cache LLM responses by semantic similarity of the user query."""

    name = "cache"

    def __init__(self) -> None:
        self._settings = get_cache_settings()
        self._stats = CacheStats()
        # Track followup signals per cache entry: entry_id -> {count, last_similarity}
        self._followup_tracker: dict[str, dict[str, Any]] = {}

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    @property
    def stats(self) -> CacheStats:
        mgr = get_vector_store_manager()
        self._stats.entries_by_tenant = {
            tenant: s.count for tenant, s in mgr.all_stats().items()
        }
        return self._stats

    def lookup(
        self,
        request: ChatCompletionRequest,
        context: PipelineContext,
    ) -> Optional[ChatCompletionResponse]:
        """Check if a semantically similar request is cached.

        Returns cached response if found (cache hit), None otherwise (cache miss).
        """
        if not self._settings.enabled:
            return None

        model = get_embedding_model()
        if not model.loaded:
            return None

        user_message = extract_user_message(request)
        if not user_message:
            self._stats.misses += 1
            return None

        try:
            mgr = get_vector_store_manager(dimension=model.dimension)
            store = mgr.get_store(f"cache:{context.tenant}")

            if store.count == 0:
                self._stats.misses += 1
                return None

            query_embedding = model.encode_single(user_message, normalize=True)
            results = store.search(
                query_embedding,
                k=1,
                threshold=self._settings.similarity_threshold,
            )

            if not results:
                self._stats.misses += 1
                return None

            hit = results[0]
            metadata = hit.metadata

            # Check TTL
            cached_at = metadata.get("cached_at", 0)
            ttl = metadata.get("ttl", self._settings.default_ttl_seconds)
            age = time.time() - cached_at
            if age > ttl:
                # Expired — remove and miss
                store.remove(hit.id)
                self._stats.misses += 1
                self._stats.evictions += 1
                return None

            # Build response from cache
            response = self._build_response(metadata, request.model)
            self._stats.hits += 1

            logger.info(
                '{"event":"cache_hit","tenant":"%s","score":%.3f,"entry_id":"%s","age_s":%.0f}',
                context.tenant, hit.score, hit.id, age,
            )
            return response

        except Exception:
            logger.warning("Cache lookup failed — treating as miss", exc_info=True)
            self._stats.misses += 1
            return None

    def store(
        self,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
        context: PipelineContext,
    ) -> None:
        """Store a response in the cache after successful LLM call."""
        if not self._settings.enabled:
            return

        model = get_embedding_model()
        if not model.loaded:
            return

        user_message = extract_user_message(request)
        if not user_message:
            return

        # Don't cache streaming or empty responses
        if not response.choices:
            return
        response_text = response.choices[0].message.content if response.choices[0].message else None
        if not response_text:
            return

        try:
            mgr = get_vector_store_manager(dimension=model.dimension)
            store = mgr.get_store(f"cache:{context.tenant}")

            query_embedding = model.encode_single(user_message, normalize=True)
            entry_id = str(uuid.uuid4())[:12]

            # Determine TTL based on detected intent
            ttl = self._resolve_ttl(context)

            metadata = {
                "cached_at": time.time(),
                "ttl": ttl,
                "response_text": response_text,
                "model": response.model,
                "usage": response.usage.model_dump() if response.usage else None,
                "user_message_preview": user_message[:100],
            }

            store.add(entry_id, query_embedding, metadata)

            logger.debug(
                '{"event":"cache_store","tenant":"%s","entry_id":"%s","ttl":%d}',
                context.tenant, entry_id, ttl,
            )
        except Exception:
            logger.warning("Cache store failed — non-critical", exc_info=True)

    def record_followup(self, tenant: str, previous_entry_id: str, followup_similarity: float) -> None:
        """Record a followup signal for a cached entry.

        Multi-signal invalidation:
        - followup_count >= threshold → invalidate
        - followup + low similarity to cached response → invalidate
        """
        key = f"{tenant}:{previous_entry_id}"
        if key not in self._followup_tracker:
            self._followup_tracker[key] = {"count": 0, "low_similarity": False}

        tracker = self._followup_tracker[key]
        tracker["count"] += 1

        if followup_similarity < 0.3:
            tracker["low_similarity"] = True

        # Multi-signal check
        should_invalidate = False
        reason = ""

        if tracker["count"] >= self._settings.followup_threshold:
            should_invalidate = True
            reason = f"followup_count={tracker['count']}"
        elif tracker["count"] >= 1 and tracker["low_similarity"]:
            should_invalidate = True
            reason = f"followup+low_similarity"

        if should_invalidate:
            try:
                mgr = get_vector_store_manager()
                store = mgr.get_store(f"cache:{tenant}")
                store.remove(previous_entry_id)
                del self._followup_tracker[key]
                self._stats.invalidations += 1
                logger.info(
                    '{"event":"cache_invalidated","tenant":"%s","entry":"%s","reason":"%s"}',
                    tenant, previous_entry_id, reason,
                )
            except Exception:
                logger.warning("Cache invalidation failed", exc_info=True)

    def delete_tenant(self, tenant: str) -> None:
        """Delete all cache data for a tenant (LGPD)."""
        mgr = get_vector_store_manager()
        mgr.delete_tenant(f"cache:{tenant}")
        # Clean followup tracker
        prefix = f"{tenant}:"
        keys_to_remove = [k for k in self._followup_tracker if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._followup_tracker[k]

    def _resolve_ttl(self, context: PipelineContext) -> int:
        """Determine cache TTL based on detected intent."""
        settings = self._settings
        intent = context.metadata.get("detected_intent", "")
        intent_lower = intent.lower() if intent else ""

        if any(k in intent_lower for k in ("greeting", "farewell", "thanks", "factual")):
            return settings.ttl_factual
        if any(k in intent_lower for k in ("creative", "write", "generate", "story")):
            return settings.ttl_creative
        if any(k in intent_lower for k in ("code", "implement", "debug", "function")):
            return settings.ttl_code

        return settings.default_ttl_seconds

    @staticmethod
    def _build_response(metadata: dict, request_model: str) -> ChatCompletionResponse:
        """Build a ChatCompletionResponse from cached metadata."""
        from aion.shared.schemas import ChatCompletionChoice, UsageInfo

        return ChatCompletionResponse(
            id=f"cache-{uuid.uuid4().hex[:8]}",
            model=metadata.get("model", request_model),
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=metadata["response_text"],
                    ),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(**metadata["usage"]) if metadata.get("usage") else None,
        )


# ── Singleton ──

_instance: Optional[SemanticCache] = None


def get_cache() -> SemanticCache:
    global _instance
    if _instance is None:
        _instance = SemanticCache()
    return _instance
