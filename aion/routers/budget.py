"""Budget router: /v1/budget/{tenant_id}."""

from __future__ import annotations

import os
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from aion.shared.budget import BudgetConfig, get_budget_store

logger = logging.getLogger("aion")

router = APIRouter()


def _error_response(status: int, message: str, code: str, error_type: str = "api_error") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


@router.put("/v1/budget/{tenant_id}", tags=["Control Plane"])
async def set_budget(tenant_id: str, payload: dict, request: Request):
    """Configure budget cap for a tenant (daily/monthly, block or downgrade on cap)."""
    try:
        config = BudgetConfig(tenant=tenant_id, **payload)
    except Exception as e:
        return _error_response(422, f"Invalid budget config: {e}", "validation_error", "invalid_request_error")
    await get_budget_store().set_config(config)
    return {"tenant": tenant_id, "status": "configured", "config": config.model_dump()}


@router.get("/v1/budget/{tenant_id}/status", tags=["Observability"])
async def get_budget_status(tenant_id: str):
    """Current budget spend and cap status for a tenant."""
    store = get_budget_store()
    config = await store.get_config(tenant_id)
    today_spend = await store.get_today_spend(tenant_id)
    state = await store.get_state(tenant_id)
    return {
        "tenant": tenant_id,
        "today_spend": round(today_spend, 6),
        "month_spend": round(state.month_spend, 6),
        "daily_cap": config.daily_cap if config else None,
        "monthly_cap": config.monthly_cap if config else None,
        "daily_cap_pct": round(today_spend / config.daily_cap, 4) if config and config.daily_cap else None,
        "cap_reached": state.cap_reached_today,
        "alert_active": today_spend >= (config.daily_cap or 0) * (config.alert_threshold if config else 0.8) if config and config.daily_cap else False,
        "on_cap_reached": config.on_cap_reached if config else None,
        "budget_enabled": os.environ.get("AION_BUDGET_ENABLED", "").lower() in ("true", "1"),
    }
