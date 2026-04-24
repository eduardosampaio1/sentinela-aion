"""Threat detector — cross-turn attack pattern analysis.

Analyzes TurnContext windows to detect sophisticated multi-turn attack patterns
that would not be visible from any single message in isolation.

Redis key: aion:threat:{tenant}:{session_id}  TTL: 24h
"""

from __future__ import annotations

import json
import logging
import os
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger("aion.estixe.threat_detector")

_TTL_SECONDS = 86400  # 24h


class ThreatPattern(str, Enum):
    PROGRESSIVE_BYPASS = "progressive_bypass"
    # risk_score climbing across turns toward threshold
    INTENT_MUTATION = "intent_mutation"
    # high-risk intent after a safe-looking opener
    THRESHOLD_PROBING = "threshold_probing"
    # many similar messages with small variations (classifier evasion)
    AUTHORITY_ESCALATION = "authority_escalation"
    # "como admin/root/sistema..." after a prior block


class ThreatSignal(BaseModel):
    session_id: str
    tenant: str
    pattern: ThreatPattern
    confidence: float
    detected_at: float
    turns_analyzed: int
    recommended_action: str  # "monitor" | "escalate_threshold" | "block_session"


def _analyze(turns: list) -> Optional[ThreatSignal]:
    """Analyze a list of TurnSummary objects for threat patterns.

    Returns a ThreatSignal if a pattern is detected, else None.
    """
    if len(turns) < 2:
        return None

    risk_scores = [t.risk_score for t in turns]
    intents = [t.intent or "" for t in turns]
    decisions = [t.decision for t in turns]

    # INTENT_MUTATION: benign opener followed by high-risk score (2+ turns, sudden jump).
    # Checked before PROGRESSIVE_BYPASS because it's more specific.
    if len(risk_scores) >= 2 and risk_scores[0] < 0.3 and risk_scores[-1] >= 0.6:
        return ThreatSignal(
            session_id="",
            tenant="",
            pattern=ThreatPattern.INTENT_MUTATION,
            confidence=round(min(0.95, 0.6 + (risk_scores[-1] - 0.6)), 3),
            detected_at=time.time(),
            turns_analyzed=len(turns),
            recommended_action="escalate_threshold",
        )

    # PROGRESSIVE_BYPASS: gradual risk escalation across ≥3 turns (incremental probing).
    if len(risk_scores) >= 3:
        if all(risk_scores[i] < risk_scores[i + 1] for i in range(len(risk_scores) - 1)):
            if risk_scores[-1] > 0.4:
                conf = min(0.95, 0.5 + risk_scores[-1])
                return ThreatSignal(
                    session_id="",
                    tenant="",
                    pattern=ThreatPattern.PROGRESSIVE_BYPASS,
                    confidence=round(conf, 3),
                    detected_at=time.time(),
                    turns_analyzed=len(turns),
                    recommended_action="escalate_threshold" if risk_scores[-1] < 0.7 else "block_session",
                )

    # AUTHORITY_ESCALATION: any prior block, last intent contains authority keywords
    authority_keywords = ("admin", "root", "sistema", "system", "override", "bypass", "sudo")
    if "block" in decisions[:-1]:
        last_intent = intents[-1].lower()
        if any(kw in last_intent for kw in authority_keywords):
            return ThreatSignal(
                session_id="",
                tenant="",
                pattern=ThreatPattern.AUTHORITY_ESCALATION,
                confidence=0.85,
                detected_at=time.time(),
                turns_analyzed=len(turns),
                recommended_action="block_session",
            )

    # THRESHOLD_PROBING: multiple turns with same non-empty intent but no bypass
    non_empty_intents = [i for i in intents if i]
    if len(non_empty_intents) >= 2:
        from collections import Counter
        counts = Counter(non_empty_intents)
        most_common_intent, most_common_count = counts.most_common(1)[0]
        if most_common_count >= 2 and all(d != "bypass" for d in decisions):
            return ThreatSignal(
                session_id="",
                tenant="",
                pattern=ThreatPattern.THRESHOLD_PROBING,
                confidence=round(min(0.90, 0.5 + most_common_count * 0.1), 3),
                detected_at=time.time(),
                turns_analyzed=len(turns),
                recommended_action="monitor",
            )

    return None


class ThreatStore:
    """Redis-backed storage for ThreatSignals. Fail-open."""

    def __init__(self) -> None:
        self._redis_client = None
        self._redis_last_failure: float = 0.0
        self._redis_retry_interval: float = 10.0

    async def get(self, tenant: str, session_id: str) -> Optional[ThreatSignal]:
        r = await self._get_redis()
        if r is None:
            return None
        try:
            key = f"aion:threat:{tenant}:{session_id}"
            raw = await r.get(key)
            if raw:
                return ThreatSignal(**json.loads(raw))
        except Exception:
            logger.debug("ThreatStore.get failed (non-critical)", exc_info=True)
        return None

    async def save(self, signal: ThreatSignal) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            key = f"aion:threat:{signal.tenant}:{signal.session_id}"
            await r.setex(key, _TTL_SECONDS, signal.model_dump_json())
        except Exception:
            logger.debug("ThreatStore.save failed (non-critical)", exc_info=True)

    async def list_active(self, tenant: str) -> list[ThreatSignal]:
        """Returns all active threat signals for a tenant (scan-based, for admin use)."""
        r = await self._get_redis()
        if r is None:
            return []
        signals: list[ThreatSignal] = []
        try:
            pattern = f"aion:threat:{tenant}:*"
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=100)
                for key in keys:
                    raw = await r.get(key)
                    if raw:
                        try:
                            signals.append(ThreatSignal(**json.loads(raw)))
                        except Exception:
                            pass
                if cursor == 0:
                    break
        except Exception:
            logger.debug("ThreatStore.list_active failed (non-critical)", exc_info=True)
        return signals

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


class ThreatDetector:
    """Analyzes TurnContext to detect multi-turn attack patterns."""

    def __init__(self) -> None:
        self._store = ThreatStore()

    async def analyze(
        self, tenant: str, session_id: str, turns: list
    ) -> Optional[ThreatSignal]:
        """Analyze turns and persist signal if detected. Returns signal or None."""
        signal = _analyze(turns)
        if signal is None:
            return None
        signal.session_id = session_id
        signal.tenant = tenant
        await self._store.save(signal)
        logger.info(
            "Threat detected: tenant=%s session=%s pattern=%s confidence=%.3f action=%s",
            tenant, session_id, signal.pattern, signal.confidence, signal.recommended_action,
        )
        return signal

    async def get_active(self, tenant: str) -> list[ThreatSignal]:
        return await self._store.list_active(tenant)


_detector: Optional[ThreatDetector] = None


def get_threat_detector() -> ThreatDetector:
    global _detector
    if _detector is None:
        _detector = ThreatDetector()
    return _detector
