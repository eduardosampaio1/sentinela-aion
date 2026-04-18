"""Behavior Dial — parametric control of AI behavior in real-time.

Storage: Redis (if configured) with in-memory fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from aion.shared.schemas import ChatCompletionRequest, ChatMessage

logger = logging.getLogger("aion.metis.behavior")

# In-memory fallback (used when Redis unavailable)
_behavior_store: dict[str, "BehaviorConfig"] = {}
_redis_client = None
_redis_available = False


class BehaviorConfig(BaseModel):
    """Behavior dial settings."""
    objectivity: int = Field(default=50, ge=0, le=100)
    density: int = Field(default=50, ge=0, le=100)
    explanation: int = Field(default=50, ge=0, le=100)
    cost_target: str = Field(default="medium")  # free | low | medium | high
    formality: int = Field(default=50, ge=0, le=100)


async def _get_redis():
    """Get or create Redis client (lazy init)."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None

    from aion.config import get_settings
    settings = get_settings()
    if not settings.redis_url:
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=2.0
        )
        await _redis_client.ping()
        _redis_available = True
        logger.info("Behavior store: Redis connected")
        return _redis_client
    except Exception:
        _redis_available = False
        logger.warning("Behavior store: Redis unavailable, using in-memory fallback")
        return None


class BehaviorDial:
    """Manages behavior settings per tenant. Redis with local fallback."""

    _REDIS_PREFIX = "aion:behavior:"
    _REDIS_TTL = 86400 * 7  # 7 days

    async def get(self, tenant: str = "default") -> Optional[BehaviorConfig]:
        r = await _get_redis()
        if r:
            try:
                data = await r.get(f"{self._REDIS_PREFIX}{tenant}")
                if data:
                    return BehaviorConfig(**json.loads(data))
                return None
            except Exception:
                logger.warning("Redis read failed, falling back to local")

        return _behavior_store.get(tenant)

    async def set(self, config: BehaviorConfig, tenant: str = "default") -> None:
        # Always write to local (fallback)
        _behavior_store[tenant] = config

        r = await _get_redis()
        if r:
            try:
                await r.setex(
                    f"{self._REDIS_PREFIX}{tenant}",
                    self._REDIS_TTL,
                    json.dumps(config.model_dump()),
                )
            except Exception:
                logger.warning("Redis write failed, stored locally only")

        logger.info("Behavior updated for tenant '%s' (%d fields)", tenant, len(config.model_dump()))

    async def delete(self, tenant: str = "default") -> None:
        _behavior_store.pop(tenant, None)

        r = await _get_redis()
        if r:
            try:
                await r.delete(f"{self._REDIS_PREFIX}{tenant}")
            except Exception:
                pass

    def apply_to_request(
        self, request: ChatCompletionRequest, config: BehaviorConfig
    ) -> ChatCompletionRequest:
        """Inject behavior instructions into the system prompt AND adjust model parameters.

        Two-layer control:
        1. Prompt instructions (soft — model may ignore)
        2. Parameter mapping (hard — guaranteed effect)
        """
        modified = request.model_copy(deep=True)

        # Layer 1: Prompt instructions
        instructions = self._build_instructions(config)
        if instructions:
            system_found = False
            for msg in modified.messages:
                if msg.role == "system":
                    msg.content = (msg.content or "") + "\n\n" + instructions
                    system_found = True
                    break

            if not system_found:
                modified.messages.insert(
                    0, ChatMessage(role="system", content=instructions)
                )

        # Layer 2: Parameter mapping (hard guarantees)
        modified = self._apply_parameters(modified, config)

        return modified

    @staticmethod
    def _apply_parameters(
        request: ChatCompletionRequest, config: BehaviorConfig
    ) -> ChatCompletionRequest:
        """Map behavior settings to real model parameters.

        Only REDUCES parameters (more constrained) — never overrides user-provided
        values with LESS constrained ones. If user explicitly set temperature=0.1,
        we don't raise it to 0.7.
        """
        # Objectivity → temperature cap
        if config.objectivity >= 80:
            cap = 0.3
            if request.temperature is None or request.temperature > cap:
                request.temperature = cap
            if request.top_p is None or request.top_p > 0.8:
                request.top_p = 0.8
        elif config.objectivity >= 60:
            cap = 0.6
            if request.temperature is None or request.temperature > cap:
                request.temperature = cap

        # Density → max_tokens cap
        if config.density >= 80:
            cap = 500
            if request.max_tokens is None or request.max_tokens > cap:
                request.max_tokens = cap

        # Cost target → aggressive caps
        if config.cost_target == "free":
            if request.max_tokens is None or request.max_tokens > 100:
                request.max_tokens = 100
            request.temperature = 0.0  # deterministic = cacheable
        elif config.cost_target == "low":
            cap = 300
            if request.max_tokens is None or request.max_tokens > cap:
                request.max_tokens = cap

        return request

    @staticmethod
    def _build_instructions(config: BehaviorConfig) -> str:
        parts = []

        if config.objectivity >= 80:
            parts.append(
                "Be extremely concise and direct. No filler words, no pleasantries, "
                "no unnecessary context. Answer in the minimum number of words possible."
            )
        elif config.objectivity >= 60:
            parts.append("Be direct and objective. Avoid unnecessary elaboration.")
        elif config.objectivity <= 20:
            parts.append("Be thorough and consultative. Explain your reasoning and provide context.")

        if config.density >= 80:
            parts.append("Use telegraphic style. Bullet points preferred over paragraphs.")
        elif config.density >= 60:
            parts.append("Keep responses compact. Prefer short paragraphs.")

        if config.explanation >= 80:
            parts.append("Do not explain your reasoning. Just give the answer.")
        elif config.explanation <= 20:
            parts.append("Explain your reasoning step by step.")

        if config.formality >= 80:
            parts.append("Use casual, informal language.")
        elif config.formality <= 20:
            parts.append("Use formal, professional language.")

        if config.cost_target == "low":
            parts.append("Keep your response under 100 words.")
        elif config.cost_target == "free":
            parts.append("Keep your response under 50 words. Be as brief as possible.")

        if not parts:
            return ""

        return "BEHAVIOR INSTRUCTIONS:\n" + "\n".join(f"- {p}" for p in parts)
