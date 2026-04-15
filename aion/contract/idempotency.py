"""IdempotencyCache — client-provided X-Idempotency-Key replay.

AION garante idempotencia da DECISAO, nao necessariamente do EFEITO EXTERNO.
Se action=CALL_SERVICE e o servico tem side effects, o cliente deve propagar
a idempotency-key downstream (ou garantir idempotencia no servico).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel

from aion.contract.decision import DecisionContract, SideEffectLevel

logger = logging.getLogger("aion.contract.idempotency")

_IDEMPOTENCY_TTL_SECONDS = 86400  # 24h


class CachedResult(BaseModel):
    """Persisted envelope around a prior DecisionContract + response."""
    contract: DecisionContract
    response: Optional[dict] = None  # ChatCompletionResponse.model_dump() when Transparent/Assisted
    executed: bool = False
    side_effects_possible: bool = False


def _cache_key(tenant: str, key: str) -> str:
    return f"aion:idemp:{tenant}:{key}"


class IdempotencyCache:
    """Thin wrapper over NemosStore for idempotent request replay."""

    def __init__(self) -> None:
        self._store = None

    def _get_store(self):
        if self._store is None:
            from aion.nemos import get_nemos
            self._store = get_nemos()._store
        return self._store

    async def get(self, tenant: str, key: str) -> Optional[CachedResult]:
        """Fetch a cached result if any. Returns None on miss or error."""
        try:
            store = self._get_store()
            raw = await store.get_json(_cache_key(tenant, key))
            if not raw:
                return None
            return CachedResult(**raw)
        except Exception:
            logger.debug("idempotency get failed", exc_info=True)
            return None

    async def set(
        self,
        tenant: str,
        key: str,
        contract: DecisionContract,
        response: Optional[dict] = None,
        executed: bool = False,
    ) -> None:
        """Persist a result for 24h. Fire-and-forget (errors logged)."""
        try:
            cached = CachedResult(
                contract=contract,
                response=response,
                executed=executed,
                side_effects_possible=contract.side_effect_level != SideEffectLevel.NONE,
            )
            store = self._get_store()
            await store.set_json(
                _cache_key(tenant, key),
                cached.model_dump(),
                ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
            )
        except Exception:
            logger.debug("idempotency set failed", exc_info=True)


_instance: IdempotencyCache | None = None


def get_idempotency_cache() -> IdempotencyCache:
    global _instance
    if _instance is None:
        _instance = IdempotencyCache()
    return _instance
