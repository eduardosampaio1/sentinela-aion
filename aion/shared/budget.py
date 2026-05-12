"""BudgetCap — hard stop de custo por tenant.

Bloqueia ou faz downgrade de modelo quando o tenant atinge o cap diário/mensal.
Integrado no pipeline pré-LLM, antes de forward_request().

Redis keys:
  aion:budget:{tenant}:config  → JSON (BudgetConfig), TTL ∞
  aion:budget:{tenant}:state   → JSON (BudgetState), TTL ∞

Endpoints: PUT /v1/budget/{tenant}, GET /v1/budget/{tenant}/status
Feature flag: AION_BUDGET_ENABLED=true
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger("aion.budget")


class BudgetConfig(BaseModel):
    tenant: str
    daily_cap: Optional[float] = None       # USD; None = sem limite
    monthly_cap: Optional[float] = None
    # F-16: ceiling for a SINGLE request (estimated cost). Rejects with 402 / 429
    # before the LLM is invoked when the prompt would exceed this amount on the
    # selected model. None = no per-request cap (legacy behavior).
    per_request_max_cost_usd: Optional[float] = None
    alert_threshold: float = 0.80           # alerta em X% do cap
    on_cap_reached: str = "downgrade"       # "downgrade" | "block"
    fallback_model: Optional[str] = None    # modelo mais barato ao atingir cap
    alert_webhook_url: Optional[str] = None # POST when alert_threshold crossed


class BudgetState(BaseModel):
    tenant: str
    today_spend: float = 0.0
    month_spend: float = 0.0
    alert_sent_today: bool = False
    cap_reached_today: bool = False
    last_updated: float = 0.0


class BudgetExceededError(Exception):
    """Raised when budget cap is reached and on_cap_reached == 'block'."""
    def __init__(self, tenant: str, cap_type: str, spend: float, cap: float) -> None:
        self.tenant = tenant
        self.cap_type = cap_type
        self.spend = spend
        self.cap = cap
        super().__init__(
            f"Budget cap reached for tenant '{tenant}': "
            f"{cap_type} spend ${spend:.4f} >= cap ${cap:.4f}"
        )


class BudgetStore:
    """Persiste BudgetConfig e BudgetState no Redis. Fail-open."""

    def __init__(self) -> None:
        self._redis_client = None
        self._redis_last_failure: float = 0.0
        self._redis_retry_interval: float = 10.0

    async def get_config(self, tenant: str) -> Optional[BudgetConfig]:
        r = await self._get_redis()
        if r is None:
            return None
        try:
            raw = await r.get(f"aion:budget:{tenant}:config")
            if raw:
                return BudgetConfig(**json.loads(raw))
        except Exception:
            logger.debug("BudgetStore.get_config failed", exc_info=True)
        return None

    async def set_config(self, config: BudgetConfig) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.set(f"aion:budget:{config.tenant}:config", config.model_dump_json())
        except Exception:
            logger.debug("BudgetStore.set_config failed", exc_info=True)

    async def get_state(self, tenant: str) -> BudgetState:
        r = await self._get_redis()
        if r is None:
            return BudgetState(tenant=tenant)
        try:
            raw = await r.get(f"aion:budget:{tenant}:state")
            if raw:
                return BudgetState(**json.loads(raw))
        except Exception:
            logger.debug("BudgetStore.get_state failed", exc_info=True)
        return BudgetState(tenant=tenant)

    async def record_spend(self, tenant: str, cost: float) -> None:
        """Adiciona custo ao estado. Chamado post-LLM (fire-and-forget).

        Daily spend uses a dedicated Redis key with INCRBYFLOAT for atomic
        increment — prevents the race condition where two concurrent requests
        both read the same today_spend value and overwrite each other's write.
        The daily key auto-expires after 2 days so no manual cleanup is needed.
        """
        r = await self._get_redis()
        if r is None:
            return
        try:
            today = _today_key()
            daily_key = f"aion:budget:{tenant}:daily:{today}"
            month_key = f"aion:budget:{tenant}:monthly"

            pipe = r.pipeline()
            # Atomic increment — safe under concurrent requests
            pipe.incrbyfloat(daily_key, cost)
            pipe.expire(daily_key, 172800)  # 2 days TTL
            pipe.incrbyfloat(month_key, cost)
            pipe.expire(month_key, 93 * 86400)  # ~3 months
            await pipe.execute()

            # Update metadata (non-atomic is fine — flags are advisory only)
            state_key = f"aion:budget:{tenant}:state"
            raw = await r.get(state_key)
            state = BudgetState(tenant=tenant)
            if raw:
                try:
                    state = BudgetState(**json.loads(raw))
                except Exception:
                    pass
            state.last_updated = time.time()
            data = state.model_dump()
            data["_day"] = today
            await r.set(state_key, json.dumps(data))
        except Exception:
            logger.debug("BudgetStore.record_spend failed", exc_info=True)

    async def get_today_spend(self, tenant: str) -> float:
        """Retorna gasto do dia atual usando chave atômica INCRBYFLOAT.

        Falls back to NEMOS EconomicsBucket when Redis is unavailable.
        Falls back to JSON state blob for backward compatibility with
        data written by the old record_spend (before the atomic refactor).
        """
        r = await self._get_redis()
        if r is None:
            return await self._nemos_today_spend(tenant)
        try:
            today = _today_key()
            daily_key = f"aion:budget:{tenant}:daily:{today}"
            raw = await r.get(daily_key)
            if raw is not None:
                return float(raw)
            # Backward compat: check old JSON state blob
            state_raw = await r.get(f"aion:budget:{tenant}:state")
            if state_raw:
                data = json.loads(state_raw)
                if data.get("_day") == today:
                    return float(data.get("today_spend", 0.0))
        except Exception:
            pass
        return await self._nemos_today_spend(tenant)

    async def _nemos_today_spend(self, tenant: str) -> float:
        """Fallback: lê EconomicsBucket do NEMOS."""
        try:
            from aion.nemos import get_nemos
            econ = await get_nemos().get_economics(tenant)
            if econ:
                return float(econ.total_actual_cost)
        except Exception:
            pass
        return 0.0

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


def _today_key() -> str:
    from datetime import date
    return date.today().isoformat()


async def check_budget(tenant: str, context) -> None:
    """Verifica cap antes de enviar para o LLM.

    Se cap atingido e on_cap_reached == 'block' → levanta BudgetExceededError.
    Se cap atingido e on_cap_reached == 'downgrade' → sobreescreve context.selected_model.
    Fail-open: se store falhar, permite request.

    F-16: também rejeita 402 ANTES da chamada LLM se o custo estimado da request
    individual exceder per_request_max_cost_usd — protege o cliente contra um
    único prompt enorme consumir o cap mensal.
    """
    if os.environ.get("AION_BUDGET_ENABLED", "").lower() not in ("true", "1"):
        return
    store = get_budget_store()
    try:
        config = await store.get_config(tenant)
        if config is None:
            return

        # F-16: per-request cap — verificar antes do daily/monthly.
        if config.per_request_max_cost_usd is not None:
            est = float(context.metadata.get("estimated_cost", 0.0) or 0.0)
            if est > config.per_request_max_cost_usd:
                logger.warning(
                    "Per-request cost cap reached: tenant=%s estimated=%.6f cap=%.6f",
                    tenant, est, config.per_request_max_cost_usd,
                )
                raise BudgetExceededError(
                    tenant, "per_request", est, config.per_request_max_cost_usd,
                )

        today_spend = await store.get_today_spend(tenant)

        if config.daily_cap is not None and today_spend >= config.daily_cap:
            logger.warning(
                "Budget cap reached: tenant=%s daily_spend=%.4f cap=%.4f",
                tenant, today_spend, config.daily_cap,
            )
            if config.on_cap_reached == "block":
                raise BudgetExceededError(tenant, "daily", today_spend, config.daily_cap)
            # downgrade
            if config.fallback_model:
                context.selected_model = config.fallback_model
                context.metadata["budget_downgraded"] = True
                context.metadata["budget_cap_type"] = "daily"
            return

        # Alert threshold
        if config.daily_cap and today_spend >= config.daily_cap * config.alert_threshold:
            context.metadata["budget_alert"] = True
            pct = round(today_spend / config.daily_cap, 3)
            context.metadata["budget_alert_pct"] = pct
            if config.alert_webhook_url:
                _fire_budget_webhook(config, today_spend, pct)

    except BudgetExceededError:
        raise
    except Exception:
        logger.debug("check_budget failed (fail-open)", exc_info=True)


def _fire_budget_webhook(config: BudgetConfig, today_spend: float, pct: float) -> None:
    """POST budget alert to webhook URL (fire-and-forget in a thread, non-blocking)."""
    import threading

    payload = {
        "tenant": config.tenant,
        "event": "budget_alert",
        "today_spend_usd": round(today_spend, 6),
        "daily_cap_usd": config.daily_cap,
        "cap_pct": pct,
        "alert_threshold": config.alert_threshold,
        "on_cap_reached": config.on_cap_reached,
    }

    def _post() -> None:
        try:
            import urllib.request
            import json as _json
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(
                config.alert_webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "AION-Budget/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            logger.debug("Budget webhook delivery failed (non-critical)", exc_info=True)

    threading.Thread(target=_post, daemon=True).start()


_store: Optional[BudgetStore] = None


def get_budget_store() -> BudgetStore:
    global _store
    if _store is None:
        _store = BudgetStore()
    return _store
