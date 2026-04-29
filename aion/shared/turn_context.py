"""TurnContext — lightweight multi-turn session state.

Armazena os últimos 3 turnos da conversa no Redis por session_id derivado
do conteúdo. Fail-open: se Redis estiver indisponível, pipeline continua
como hoje (stateless).

Redis key: aion:session_ctx:{tenant}:{session_id}  TTL: 10 min
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel

from aion.config import get_metis_settings

if TYPE_CHECKING:
    from aion.shared.schemas import ChatCompletionRequest

logger = logging.getLogger("aion.turn_context")
# _MAX_TURNS and _TTL_SECONDS read from MetisSettings at call time


class TurnSummary(BaseModel):
    """Snapshot imutável de um turno do pipeline."""
    intent: Optional[str] = None
    complexity: float = 0.0
    model_used: str = ""
    pii_types: list[str] = []
    risk_score: float = 0.0
    decision: str = "continue"  # "continue" | "bypass" | "block"
    timestamp: float = 0.0


class TurnContext(BaseModel):
    """Janela deslizante dos últimos _MAX_TURNS turnos."""
    session_id: str
    tenant: str
    turns: list[TurnSummary] = []
    last_updated: float = 0.0

    def add_turn(self, turn: TurnSummary) -> None:
        max_turns = get_metis_settings().turn_context_max_turns
        self.turns.append(turn)
        if len(self.turns) > max_turns:
            self.turns = self.turns[-max_turns:]
        self.last_updated = time.time()

    @property
    def last_turn(self) -> Optional[TurnSummary]:
        return self.turns[-1] if self.turns else None

    @property
    def max_risk_score(self) -> float:
        return max((t.risk_score for t in self.turns), default=0.0)

    @property
    def last_intent(self) -> Optional[str]:
        for t in reversed(self.turns):
            if t.intent:
                return t.intent
        return None

    @property
    def max_complexity(self) -> float:
        return max((t.complexity for t in self.turns), default=0.0)


_EXPLICIT_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def derive_session_id(
    tenant: str,
    messages: list,
    explicit_id: str | None = None,
) -> str:
    """Deriva session_id estável.

    Prefere ``explicit_id`` (X-Aion-Session-Id header) para evitar colisão
    de birthday quando dois usuários do mesmo tenant começam com a mesma frase.
    Fallback: hash SHA-256 completo (64 hex) da âncora tenant + primeira mensagem.
    """
    if explicit_id and _EXPLICIT_ID_RE.match(explicit_id[:256]):
        return explicit_id[:64]
    anchor = ""
    if messages:
        first = messages[0]
        content = getattr(first, "content", "") or ""
        anchor = str(content)[:100]
    raw = f"{tenant}:{anchor}"
    return hashlib.sha256(raw.encode()).hexdigest()  # full 64 hex — no truncation


class TurnContextStore:
    """Lê/escreve TurnContext no Redis. Fail-open."""

    def __init__(self) -> None:
        self._redis_client = None
        self._redis_last_failure: float = 0.0
        self._redis_retry_interval: float = 10.0

    async def load(self, tenant: str, session_id: str) -> Optional[TurnContext]:
        """Carrega TurnContext do Redis. Retorna None em falha (fail-open)."""
        r = await self._get_redis()
        if r is None:
            return None
        try:
            key = f"aion:session_ctx:{tenant}:{session_id}"
            raw = await r.get(key)
            if raw:
                data = json.loads(raw)
                return TurnContext(**data)
        except Exception:
            logger.debug("TurnContextStore.load failed (non-critical)", exc_info=True)
        return None

    async def save(self, tenant: str, ctx: TurnContext) -> None:
        """Persiste TurnContext. Fire-and-forget — falha não bloqueia pipeline."""
        r = await self._get_redis()
        if r is None:
            return
        try:
            key = f"aion:session_ctx:{tenant}:{ctx.session_id}"
            await r.setex(key, get_metis_settings().turn_context_ttl_seconds, ctx.model_dump_json())
        except Exception:
            logger.debug("TurnContextStore.save failed (non-critical)", exc_info=True)

    async def _get_redis(self):
        if self._redis_last_failure > 0 and (time.time() - self._redis_last_failure) < self._redis_retry_interval:
            return None
        if self._redis_client is not None:
            return self._redis_client
        import os
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return None
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                url, decode_responses=True,
                socket_timeout=0.5, socket_connect_timeout=0.5,
            )
            await client.ping()
            self._redis_client = client
            self._redis_last_failure = 0.0
            return client
        except Exception:
            self._redis_last_failure = time.time()
            self._redis_client = None
            return None


# Singleton
_store: Optional[TurnContextStore] = None


def get_turn_context_store() -> TurnContextStore:
    global _store
    if _store is None:
        _store = TurnContextStore()
    return _store
