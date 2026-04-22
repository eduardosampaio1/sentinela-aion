"""Velocity detection for ESTIXE — probing / brute-force attack mitigation.

Tracks block events per tenant in a rolling window. When a tenant accumulates
`block_threshold` blocks within `window_seconds`, all risk thresholds are
tightened by `tighten_delta` for subsequent requests in that window.

Backend selection (lazy, on first call):
  - If REDIS_URL is configured and reachable -> Redis sorted-set per tenant.
    Survives process restart, shared across AION replicas (the correct mode for prod).
  - Otherwise -> in-process deque per tenant. Works for single-process dev/sim.

Redis layout:
  Key:   aion:velocity:<tenant>           (sorted set)
  Score: event timestamp (float seconds since epoch)
  Member: unique id to allow multiple entries with same timestamp
  TTL:   2 * window_seconds (auto-clean stale tenants)

All public methods are async. Old API was sync; call sites were migrated to await.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from aion.config import EstixeSettings
from aion.shared.schemas import PipelineContext

logger = logging.getLogger("aion.estixe.velocity")


class VelocityTracker:
    """Rolling-window block counter with automatic threshold tightening.

    Public API (async):
        await record_block(tenant)                               -> record a block event
        await recent_block_count(tenant) -> int                  -> count events in window
        await resolve_threshold_overrides(                       -> compute effective thresholds
            context, tenant_overrides, risk_defs
        ) -> dict | None
    """

    def __init__(self, settings: EstixeSettings) -> None:
        self._settings = settings
        # Local fallback — always present, used when Redis unavailable
        self._block_timestamps: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._redis_checked = False
        self._redis_available = False
        # Circuit breaker: evita hammering em Redis down
        self._redis_last_failure: float = 0.0
        self._redis_retry_interval: float = 10.0

    # ── Redis backend (lazy init) ─────────────────────────────────────────────

    async def _get_redis(self):
        """Returns Redis client if configured and reachable, else None.

        Circuit breaker: se Redis falhou em operação recente, retorna None sem retry.
        """
        # Circuit breaker ativo: skip tentativa
        if self._redis_last_failure > 0 and (time.time() - self._redis_last_failure) < self._redis_retry_interval:
            return None

        if self._redis_checked and self._redis_available:
            return getattr(self, "_client", None)

        self._redis_checked = True
        try:
            import os
            redis_url = os.environ.get("REDIS_URL", "")
            if not redis_url:
                self._redis_available = False
                return None
            import redis.asyncio as aioredis  # type: ignore
            client = aioredis.from_url(
                redis_url, decode_responses=True,
                socket_timeout=1.0, socket_connect_timeout=1.0,
            )
            await client.ping()
            self._client = client
            self._redis_available = True
            self._redis_last_failure = 0.0
            logger.info("VelocityTracker using Redis backend")
            return client
        except Exception as e:
            self._redis_available = False
            self._redis_last_failure = time.time()
            logger.info("VelocityTracker: Redis down (%s) — in-memory fallback por %.0fs",
                        type(e).__name__, self._redis_retry_interval)
            return None

    def _mark_redis_failure(self):
        """Marca Redis indisponivel apos falha em operacao."""
        self._redis_available = False
        self._redis_last_failure = time.time()

    # ── Public API ────────────────────────────────────────────────────────────

    async def record_block(self, tenant: str) -> None:
        """Record a block event timestamp for *tenant*."""
        ts = time.time()  # wall-clock for Redis cross-process compat

        # Always write local (so single-process and hybrid modes both work)
        self._block_timestamps[tenant].append(ts)

        # Also write Redis if available
        r = await self._get_redis()
        if r:
            key = f"aion:velocity:{tenant}"
            try:
                member = f"{ts}:{uuid.uuid4().hex[:8]}"
                await r.zadd(key, {member: ts})
                # Auto-prune old entries and refresh TTL
                window = self._settings.velocity_window_seconds
                await r.zremrangebyscore(key, 0, ts - window)
                await r.expire(key, window * 2)
            except Exception as e:
                self._mark_redis_failure()
                logger.warning("Redis velocity write failed, using local only: %s", e)

    async def recent_block_count(self, tenant: str) -> int:
        """Count block events for *tenant* within the rolling window.

        Uses Redis if available (shared across replicas), otherwise local deque.
        """
        window = self._settings.velocity_window_seconds
        cutoff = time.time() - window

        r = await self._get_redis()
        if r:
            key = f"aion:velocity:{tenant}"
            try:
                return await r.zcount(key, cutoff, "+inf")
            except Exception as e:
                self._mark_redis_failure()
                logger.warning("Redis velocity read failed, falling back to local: %s", e)

        # Local fallback: count timestamps within window
        # Note: local uses time.time() for consistency with Redis mode
        return sum(1 for t in self._block_timestamps[tenant] if t >= cutoff)

    async def resolve_threshold_overrides(
        self,
        context: PipelineContext,
        tenant_overrides: dict[str, float],
        risk_definitions: Any,          # list[RiskDefinition] from RiskClassifier._risks
    ) -> dict[str, float] | None:
        """Compute effective per-category threshold overrides for this request.

        Resolution order (highest precedence first):
            1. Velocity tightening (if triggered): lowers all thresholds by delta
            2. Tenant-specific overrides (from estixe_thresholds in context.metadata)
            3. YAML per-category threshold (RiskClassifier default — handled internally)

        Returns None when no overrides are active (avoids dict allocation on hot path).

        Side effect: writes velocity_alert and velocity_recent_blocks to
        context.metadata when velocity is triggered (for telemetry).
        """
        recent_blocks = await self.recent_block_count(context.tenant)
        velocity_active = (
            self._settings.velocity_enabled
            and recent_blocks >= self._settings.velocity_block_threshold
        )

        if velocity_active:
            context.metadata["velocity_alert"] = True
            context.metadata["velocity_recent_blocks"] = recent_blocks
            logger.warning(
                "VELOCITY ALERT: tenant='%s' — %d blocks in last %ds → "
                "tightening thresholds by %.2f",
                context.tenant,
                recent_blocks,
                self._settings.velocity_window_seconds,
                self._settings.velocity_tighten_delta,
            )

        if not tenant_overrides and not velocity_active:
            return None  # no overrides — use YAML defaults

        # Start from tenant overrides, apply velocity tightening on top
        result: dict[str, float] = dict(tenant_overrides)
        if velocity_active:
            delta = self._settings.velocity_tighten_delta
            for risk in risk_definitions:
                base = result.get(risk.name, risk.threshold)
                result[risk.name] = max(0.60, base - delta)

        return result
