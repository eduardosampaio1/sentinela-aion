"""DecisionCache — cache L1+L2 do resultado do pipeline ESTIXE.

Arquitetura dois níveis:
  - L1 (in-memory LRU): por-processo, lookup ~10µs. Hit ratio alto em queries repetidas.
  - L2 (Redis, opcional): compartilhado entre workers/replicas, lookup ~1-2ms.
                          Sem ele, cada worker/replica tem cache próprio → hit_rate ∝ 1/N.
                          Com ele, hit rate compartilhado → escalabilidade real.

Hot path (fast decision, decisão em ~10µs):
  1. Check L1 → hit? return
  2. Check L2 (Redis) → hit? popular L1 + return
  3. Miss → pipeline slow path (~50ms) → popular L1 + L2

Filosofia: AION é um gate. A maioria das queries repete (saudações, ataques conhecidos,
consultas frequentes). Bater cache significa retornar em µs em vez de ms.

Chave de cache:
    sha256(version | tenant_id | normalized_input)

Invalidação:
  - reload() bump de version → todas entries ficam unreachable (safe rotate)
  - TTL individual por entrada (default 5min)
  - NÃO cachea decisões dinâmicas (velocity_alert, shadow observations)
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from aion.shared.contracts import EstixeAction, EstixeResult


@dataclass
class CachedDecision:
    """Entrada imutável do cache. Envelope sobre EstixeResult.

    Motivo: EstixeResult é mutável (tem atributos dataclass). Guardar uma
    snapshot imutável garante que múltiplas threads lendo o cache não
    corrompem estado entre si.
    """
    action: EstixeAction
    block_reason: Optional[str]
    policy_matched: tuple[str, ...]
    policy_action: Optional[str]
    pii_sanitized: bool
    pii_violations: tuple[str, ...]
    intent_detected: Optional[str]
    intent_confidence: float
    # timestamp para TTL
    created_at: float

    def to_result(self) -> EstixeResult:
        """Rehydrate para EstixeResult (mutável). Cada request recebe sua cópia."""
        r = EstixeResult(action=self.action)
        r.block_reason = self.block_reason
        r.policy_matched = list(self.policy_matched)
        r.policy_action = self.policy_action
        r.pii_sanitized = self.pii_sanitized
        r.pii_violations = list(self.pii_violations)
        r.intent_detected = self.intent_detected
        r.intent_confidence = self.intent_confidence
        return r

    @classmethod
    def from_result(cls, result: EstixeResult) -> "CachedDecision":
        return cls(
            action=result.action,
            block_reason=result.block_reason,
            policy_matched=tuple(result.policy_matched or []),
            policy_action=result.policy_action,
            pii_sanitized=result.pii_sanitized,
            pii_violations=tuple(result.pii_violations or []),
            intent_detected=result.intent_detected,
            intent_confidence=result.intent_confidence,
            created_at=time.time(),
        )


class DecisionCache:
    """LRU cache de decisões finais do pipeline ESTIXE.

    Exposto em /metrics via aion_decision_cache_* para observabilidade.

    Uso:
        cache = DecisionCache(max_size=10000, ttl_seconds=300)
        if cached := cache.get(tenant, user_message, policy_version):
            return cached.to_result()  # fast path
        # slow path — roda pipeline completo
        result = run_pipeline(...)
        cache.put(tenant, user_message, policy_version, result)
    """

    def __init__(self, max_size: int = 10_000, ttl_seconds: int = 300) -> None:
        self._cache: "OrderedDict[str, CachedDecision]" = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._hits_l1 = 0
        self._hits_l2 = 0
        self._misses = 0
        self._evictions = 0
        self._ttl_expired = 0
        self._version = "v0"  # bumped on reload() para invalidation global
        # Redis L2 state (circuit breaker)
        self._redis_client = None
        self._redis_last_failure: float = 0.0
        self._redis_retry_interval: float = 10.0

    @property
    def _hits(self) -> int:
        return self._hits_l1 + self._hits_l2

    # ── Fast hash ──
    # sha256 ~1.5µs pra mensagens curtas. Suficiente.
    def _key(self, tenant: str, normalized_input: str) -> str:
        h = hashlib.sha256()
        h.update(self._version.encode())
        h.update(b"|")
        h.update(tenant.encode())
        h.update(b"|")
        h.update(normalized_input.encode())
        return h.hexdigest()

    def get_l1(self, tenant: str, normalized_input: str) -> Optional[CachedDecision]:
        """L1 lookup apenas (in-memory). Sync. Hot path."""
        key = self._key(tenant, normalized_input)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.time() - entry.created_at > self._ttl:
            self._cache.pop(key, None)
            self._ttl_expired += 1
            return None
        self._cache.move_to_end(key)
        return entry

    async def get(self, tenant: str, normalized_input: str) -> Optional[CachedDecision]:
        """Retorna decisão. Async por causa do L2 Redis lookup.

        L1 first (~10µs) → L2 (~1-2ms) → None (miss → caller roda pipeline).
        """
        key = self._key(tenant, normalized_input)

        # L1
        entry = self._cache.get(key)
        if entry is not None:
            if time.time() - entry.created_at > self._ttl:
                self._cache.pop(key, None)
                self._ttl_expired += 1
            else:
                self._cache.move_to_end(key)
                self._hits_l1 += 1
                return entry

        # L2 — Redis
        r = await self._get_redis()
        if r is not None:
            try:
                raw = await r.get(f"aion:decision:{self._version}:{key}")
                if raw:
                    import json
                    data = json.loads(raw)
                    entry = CachedDecision(
                        action=EstixeAction(data["action"]),
                        block_reason=data.get("block_reason"),
                        policy_matched=tuple(data.get("policy_matched", [])),
                        policy_action=data.get("policy_action"),
                        pii_sanitized=data.get("pii_sanitized", False),
                        pii_violations=tuple(data.get("pii_violations", [])),
                        intent_detected=data.get("intent_detected"),
                        intent_confidence=data.get("intent_confidence", 0.0),
                        created_at=data.get("created_at", time.time()),
                    )
                    # Popula L1 para próximas chamadas
                    self._cache[key] = entry
                    self._cache.move_to_end(key)
                    while len(self._cache) > self._max_size:
                        self._cache.popitem(last=False)
                        self._evictions += 1
                    self._hits_l2 += 1
                    return entry
            except Exception:
                self._mark_redis_failure()

        self._misses += 1
        return None

    async def put(self, tenant: str, normalized_input: str, result: EstixeResult) -> None:
        """Armazena em L1 + L2. Skip se há dados dinâmicos (velocity/shadow)."""
        key = self._key(tenant, normalized_input)
        entry = CachedDecision.from_result(result)

        # L1
        self._cache[key] = entry
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
            self._evictions += 1

        # L2 — Redis (fire-and-forget, tolerante a falha)
        r = await self._get_redis()
        if r is not None:
            try:
                import json
                data = {
                    "action": entry.action.value,
                    "block_reason": entry.block_reason,
                    "policy_matched": list(entry.policy_matched),
                    "policy_action": entry.policy_action,
                    "pii_sanitized": entry.pii_sanitized,
                    "pii_violations": list(entry.pii_violations),
                    "intent_detected": entry.intent_detected,
                    "intent_confidence": entry.intent_confidence,
                    "created_at": entry.created_at,
                }
                await r.setex(f"aion:decision:{self._version}:{key}", self._ttl, json.dumps(data))
            except Exception:
                self._mark_redis_failure()

    async def _get_redis(self):
        """Lazy Redis client com circuit breaker."""
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
            return None

    def _mark_redis_failure(self):
        self._redis_last_failure = time.time()
        self._redis_client = None

    def invalidate_all(self) -> None:
        """Invalida cache global. Chamado em reload de policy/taxonomy.

        Uso bump de version em vez de clear — operações em flight continuam
        seguras, entries antigas apenas viram "unreachable" e serão evictadas.
        """
        self._version = hashlib.sha256(f"{time.time()}".encode()).hexdigest()[:8]
        # Clear explícito também (evict imediato)
        self._cache.clear()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max": self._max_size,
            "hits": self._hits,
            "hits_l1": self._hits_l1,
            "hits_l2": self._hits_l2,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0.0,
            "hit_rate_l1": round(self._hits_l1 / total, 4) if total else 0.0,
            "hit_rate_l2": round(self._hits_l2 / total, 4) if total else 0.0,
            "evictions": self._evictions,
            "ttl_expired": self._ttl_expired,
            "ttl_seconds": self._ttl,
            "version": self._version,
        }
