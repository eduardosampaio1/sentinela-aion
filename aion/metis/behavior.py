"""Behavior Dial — parametric control of AI behavior in real-time.

Storage: Redis (if configured) with in-memory fallback.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import Optional

from pydantic import Field

from aion.config import get_metis_settings
from aion.shared.schemas import ChatCompletionRequest, ChatMessage
from aion.shared.strict_model import StrictModel

logger = logging.getLogger("aion.metis.behavior")

# In-memory fallback (used when Redis unavailable) — bounded LRU by tenant
# Max entries read from MetisSettings.behavior_store_max_entries at call time
_behavior_store: OrderedDict[str, "BehaviorConfig"] = OrderedDict()
_redis_client = None
_redis_available = False


class BehaviorConfig(StrictModel):
    """Behavior dial settings.

    Schema is the union of the dials used by Metis internally
    (`density`, `cost_target`) and the dials exposed by the console UI
    (`objectivity`, `verbosity`, `economy`, `confidence`, `safe_mode`).
    Sharing a single Pydantic model keeps a single source of truth and lets
    `extra="forbid"` (inherited from StrictModel) catch typos / contract
    drift loudly instead of silently discarding fields (see C2 in
    qa-evidence/console-backend-integration).

    Note: `safe_mode` here is an INT 0–100 user-facing dial (how conservative
    the model behavior should be). It is unrelated to the Kill Switch
    `safe_mode` boolean in `AionSettings.safe_mode`. Different namespaces.

    `version` is a monotonic counter incremented on every successful update.
    The console reads it via GET and sends it back in PUT — a stale version
    yields HTTP 409 from the router so concurrent edits don't last-write-wins
    (N4 fix).
    """

    # ── Backend-internal dials (consumed by metis/optimizer.py) ──
    objectivity: int = Field(default=50, ge=0, le=100)
    density: int = Field(default=50, ge=0, le=100)
    explanation: int = Field(default=50, ge=0, le=100)
    cost_target: str = Field(default="medium")  # free | low | medium | high
    formality: int = Field(default=50, ge=0, le=100)

    # ── Console UI dials (sent by routing-page slider, behavior-estimate) ──
    # Stored alongside the internal dials so the UI can roundtrip its state
    # without losing user intent. Future work can collapse `verbosity`/`density`
    # and `economy`/`cost_target` once a single canonical name is chosen.
    verbosity: int = Field(default=50, ge=0, le=100)
    economy: int = Field(default=50, ge=0, le=100)
    confidence: int = Field(default=50, ge=0, le=100)
    safe_mode: int = Field(default=50, ge=0, le=100)

    # ── Optimistic concurrency (N4 fix) ──
    # Bumped by the router on each successful PUT. Clients send the version
    # they last read in `if_version`; mismatch → 409.
    version: int = Field(default=0, ge=0)


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
    # TTL read from MetisSettings.behavior_redis_ttl_seconds

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
        ms = get_metis_settings()
        # Always write to local (fallback) — maintain LRU order and size bound
        _behavior_store[tenant] = config
        _behavior_store.move_to_end(tenant)
        while len(_behavior_store) > ms.behavior_store_max_entries:
            _behavior_store.popitem(last=False)

        r = await _get_redis()
        if r:
            try:
                await r.setex(
                    f"{self._REDIS_PREFIX}{tenant}",
                    ms.behavior_redis_ttl_seconds,
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
