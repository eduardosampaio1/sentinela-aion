"""SessionAudit — audit trail imutável por sessão de conversa.

Cada turno do pipeline gera um TurnAuditEntry armazenado no Redis.
A SessionRecord inclui assinatura HMAC-SHA256 para verificação de integridade.

Redis keys:
  aion:session_audit:{tenant}:{session_id}  → JSON (SessionRecord), TTL 90d
  aion:session_index:{tenant}               → ZSET (session_id → timestamp), TTL 90d

Endpoint de export: GET /v1/session/{id}/audit
Listagem: GET /v1/sessions/{tenant}?page=1&limit=20
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger("aion.session_audit")

_TTL_SECONDS = int(os.environ.get("AION_SESSION_AUDIT_TTL", 7_776_000))  # 90d default
_INDEX_TTL = _TTL_SECONDS + 86_400  # index vive um dia a mais que os registros
_INDEX_MAX_SIZE = 10_000  # máx de sessões no índice por tenant


_KEY_VERSION = "v1"


def _get_secret() -> str:
    return os.environ.get("AION_SESSION_AUDIT_SECRET", "")


def _sign(turns_json: str, aad: str = "") -> str:
    """HMAC-SHA256 with key_id prefix and AAD (tenant:session_id).

    Format: "kid:v1:<hexdigest>"
    AAD is prepended to the signed payload so cross-tenant forgery is impossible
    even if two sessions share identical turn data.
    Returns "" when no secret is configured.
    """
    secret = _get_secret()
    if not secret:
        return ""
    payload = f"{aad}:{turns_json}" if aad else turns_json
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"kid:{_KEY_VERSION}:{digest}"


def _verify(turns_json: str, signature: str, aad: str = "") -> bool:
    """Verify a kid-prefixed HMAC signature. Returns False for unsigned records."""
    if not signature:
        return False
    expected = _sign(turns_json, aad=aad)
    if not expected:
        return False
    return hmac.compare_digest(signature, expected)


class TurnAuditEntry(BaseModel):
    request_id: str
    timestamp: float
    user_message_hash: str      # sha256 da mensagem (não texto bruto — LGPD)
    decision: str               # continue | bypass | block
    model_used: Optional[str] = None
    pii_types_detected: list[str] = []
    risk_score: float = 0.0
    intent_detected: Optional[str] = None
    policies_matched: list[str] = []
    tokens_sent: int = 0
    tokens_received: int = 0
    latency_ms: float = 0.0


class SessionRecord(BaseModel):
    session_id: str
    tenant: str
    turns: list[TurnAuditEntry] = []
    started_at: float = 0.0
    last_activity: float = 0.0
    hmac_signature: str = ""    # HMAC-SHA256 de turns serializado; "" se sem secret

    def _aad(self) -> str:
        return f"{self.tenant}:{self.session_id}"

    def sign(self) -> None:
        turns_json = json.dumps([t.model_dump() for t in self.turns], sort_keys=True)
        self.hmac_signature = _sign(turns_json, aad=self._aad())

    def verify(self) -> bool:
        """Returns True only when signature is present and cryptographically valid."""
        if not self.hmac_signature:
            return False  # unsigned record is not verified
        turns_json = json.dumps([t.model_dump() for t in self.turns], sort_keys=True)
        return _verify(turns_json, self.hmac_signature, aad=self._aad())


def _hash_message(content: Optional[str]) -> str:
    if not content:
        return ""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class SessionAuditStore:
    """Persiste SessionRecord no Redis. Fail-open."""

    def __init__(self) -> None:
        self._redis_client = None
        self._redis_last_failure: float = 0.0
        self._redis_retry_interval: float = 10.0

    async def append_turn(
        self,
        tenant: str,
        session_id: str,
        entry: TurnAuditEntry,
    ) -> None:
        """Adiciona TurnAuditEntry à sessão. Cria SessionRecord se não existir."""
        r = await self._get_redis()
        if r is None:
            return
        try:
            key = f"aion:session_audit:{tenant}:{session_id}"
            raw = await r.get(key)
            if raw:
                try:
                    rec = SessionRecord(**json.loads(raw))
                except Exception:
                    logger.warning(
                        "SessionAudit: corrupt record for session %s/%s — starting fresh",
                        tenant, session_id,
                    )
                    rec = SessionRecord(session_id=session_id, tenant=tenant, started_at=entry.timestamp)
            else:
                rec = SessionRecord(
                    session_id=session_id,
                    tenant=tenant,
                    started_at=entry.timestamp,
                )
            rec.turns.append(entry)
            rec.last_activity = entry.timestamp
            rec.sign()

            await r.setex(key, _TTL_SECONDS, rec.model_dump_json())

            # Mantém índice de sessões por tenant (ZSET score = timestamp)
            index_key = f"aion:session_index:{tenant}"
            await r.zadd(index_key, {session_id: entry.timestamp})
            await r.expire(index_key, _INDEX_TTL)
            # Limita tamanho do índice (remove sessões mais antigas)
            size = await r.zcard(index_key)
            if size > _INDEX_MAX_SIZE:
                await r.zpopmin(index_key, size - _INDEX_MAX_SIZE)
        except Exception:
            logger.debug("SessionAuditStore.append_turn failed (non-critical)", exc_info=True)

    async def get_session(self, tenant: str, session_id: str) -> Optional[SessionRecord]:
        r = await self._get_redis()
        if r is None:
            return None
        try:
            key = f"aion:session_audit:{tenant}:{session_id}"
            raw = await r.get(key)
            if raw:
                try:
                    return SessionRecord(**json.loads(raw))
                except Exception:
                    logger.warning(
                        "SessionAudit: invalid record data for session %s/%s — returning None",
                        tenant, session_id,
                    )
                    return None
        except Exception:
            logger.debug("SessionAuditStore.get_session failed", exc_info=True)
        return None

    async def list_sessions(
        self,
        tenant: str,
        page: int = 1,
        limit: int = 20,
    ) -> list[dict]:
        """Retorna lista paginada de sessões (mais recentes primeiro)."""
        r = await self._get_redis()
        if r is None:
            return []
        try:
            index_key = f"aion:session_index:{tenant}"
            total = await r.zcard(index_key)
            offset = (page - 1) * limit
            # ZREVRANGEBYSCORE: mais recentes primeiro
            items = await r.zrevrange(index_key, offset, offset + limit - 1, withscores=True)
            result = []
            for session_id, ts in items:
                result.append({"session_id": session_id, "last_activity": ts})
            return result
        except Exception:
            logger.debug("SessionAuditStore.list_sessions failed", exc_info=True)
        return []

    async def _get_redis(self):
        if self._redis_last_failure > 0 and (time.time() - self._redis_last_failure) < self._redis_retry_interval:
            return None
        if self._redis_client is not None:
            return self._redis_client
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


_store: Optional[SessionAuditStore] = None


def get_session_audit_store() -> SessionAuditStore:
    global _store
    if _store is None:
        _store = SessionAuditStore()
    return _store
