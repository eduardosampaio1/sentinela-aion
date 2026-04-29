"""Control plane router: behavior, modules, killswitch, calibration, overrides, estixe."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from aion.config import get_settings
from aion.middleware import audit, get_overrides, set_override, clear_overrides

logger = logging.getLogger("aion")

router = APIRouter()


def _get_pipeline():
    import aion.main as _main
    return _main._pipeline


@router.put("/v1/killswitch", tags=["Control Plane"])
async def activate_killswitch(request: Request):
    """Activate SAFE_MODE — all modules bypassed, pure passthrough."""
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = body.get("reason", "manual")
    _pipeline.activate_safe_mode(reason)
    return {"status": "safe_mode_active", "reason": reason}


@router.delete("/v1/killswitch", tags=["Control Plane"])
async def deactivate_killswitch():
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    _pipeline.deactivate_safe_mode()
    return {"status": "normal_mode_restored"}


@router.get("/v1/killswitch", tags=["Control Plane"])
async def get_killswitch():
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    settings = get_settings()
    return {"safe_mode": settings.safe_mode}


@router.get("/v1/overrides", tags=["Control Plane"])
async def get_overrides_endpoint(request: Request):
    """Get current runtime overrides for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return await get_overrides(tenant)


@router.put("/v1/overrides", tags=["Control Plane"])
async def set_overrides_endpoint(request: Request):
    """Set runtime overrides. Priority: request header > tenant > global override."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    try:
        body = await request.json()
    except Exception:
        body = {}
    for k, v in body.items():
        await set_override(k, v, tenant)
    return {"status": "active", "overrides": await get_overrides(tenant)}


@router.delete("/v1/overrides", tags=["Control Plane"])
async def clear_overrides_endpoint(request: Request):
    """Clear all runtime overrides for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    await clear_overrides(tenant)
    return {"status": "cleared"}


@router.put("/v1/modules/{module_name}/toggle", tags=["Control Plane"])
async def toggle_module(module_name: str, request: Request):
    """Toggle a module on/off at runtime (Track D)."""
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    status = _pipeline._module_status.get(module_name)
    if not status:
        raise HTTPException(status_code=404, detail=f"Module '{module_name}' not found")

    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = body.get("enabled", not status.healthy)
    status.healthy = enabled
    if not enabled:
        status.consecutive_failures = get_settings().module_failure_threshold
    else:
        status.consecutive_failures = 0

    return {"module": module_name, "enabled": enabled}


@router.get("/v1/behavior", tags=["Control Plane"])
async def get_behavior(request: Request):
    from aion.metis.behavior import BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    dial = BehaviorDial()
    config = await dial.get(tenant)
    if config is None:
        return {"tenant": tenant, "behavior": None}
    return {"tenant": tenant, "behavior": config.model_dump()}


@router.put("/v1/behavior", tags=["Control Plane"])
async def set_behavior(request: Request):
    from aion.metis.behavior import BehaviorConfig, BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    body = await request.json()
    config = BehaviorConfig(**body)
    dial = BehaviorDial()
    await dial.set(config, tenant)
    return {"tenant": tenant, "behavior": config.model_dump(), "status": "active"}


@router.delete("/v1/behavior", tags=["Control Plane"])
async def delete_behavior(request: Request):
    from aion.metis.behavior import BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    dial = BehaviorDial()
    await dial.delete(tenant)
    return {"tenant": tenant, "status": "removed"}


@router.get("/v1/calibration/{tenant}", tags=["Control Plane"])
async def get_calibration(tenant: str):
    """Shadow mode calibration report for a tenant."""
    from aion.config import get_estixe_settings
    from aion.nemos import get_nemos

    estixe_cfg = get_estixe_settings()
    nemos = get_nemos()
    shadow_stats = await nemos.get_shadow_stats(tenant)

    min_requests = estixe_cfg.shadow_promote_min_requests
    min_days = estixe_cfg.shadow_promote_min_days
    max_std = estixe_cfg.shadow_promote_min_stability
    cooldown_days = estixe_cfg.shadow_promote_cooldown_days

    tenant_overrides = await get_overrides(tenant)
    tenant_thresholds: dict = tenant_overrides.get("estixe_thresholds") or {}
    shadow_mode_active = bool(tenant_overrides.get("shadow_mode"))

    categories = []
    ready_count = 0
    for category, obs in shadow_stats.items():
        current_threshold = tenant_thresholds.get(category)
        suggested = obs.suggested_threshold()
        drift_headroom = (
            round(abs(suggested - current_threshold), 3)
            if current_threshold is not None else None
        )
        cooldown_remaining = obs.cooldown_remaining_days(cooldown_days)

        gate_status = {
            "volume": obs.total_seen >= min_requests,
            "time": obs.days_monitored >= min_days,
            "stability": obs.is_stable_enough(max_std),
            "cooldown": cooldown_remaining == 0.0,
        }
        all_gates_pass = all(gate_status.values()) and not obs.promoted

        entry = {
            "category": category,
            "total_seen": obs.total_seen,
            "days_monitored": round(obs.days_monitored, 2),
            "avg_confidence": round(obs.avg_confidence, 4),
            "min_confidence": round(obs.min_confidence, 4),
            "max_confidence": round(obs.max_confidence, 4),
            "confidence_std": round(obs.confidence_std, 4),
            "stability_score": round(obs.stability_score, 3),
            "promoted": obs.promoted,
            "promoted_at": obs.promoted_at or None,
            "rollback_available": obs.promoted and obs.previous_threshold is not None,
            "cooldown_remaining_days": round(cooldown_remaining, 1),
            "current_threshold": current_threshold,
            "suggested_threshold": suggested,
            "drift_headroom": drift_headroom,
            "gates": gate_status,
            "ready_to_promote": all_gates_pass,
        }
        categories.append(entry)
        if all_gates_pass:
            ready_count += 1

    categories.sort(key=lambda c: (
        -int(c["ready_to_promote"]),
        -int(c["promoted"]),
        -c["total_seen"],
    ))

    if shadow_stats:
        try:
            from aion.shared.telemetry import beacon_shadow_stats
            asyncio.create_task(beacon_shadow_stats(tenant, shadow_stats))
        except Exception:
            pass

    return {
        "tenant": tenant,
        "shadow_mode_active": shadow_mode_active,
        "promotion_criteria": {
            "min_requests": min_requests,
            "min_days": min_days,
            "max_confidence_std": max_std,
            "cooldown_days": cooldown_days,
            "max_threshold_delta": estixe_cfg.shadow_promote_max_threshold_delta,
        },
        "total_shadow_categories": len(categories),
        "ready_to_promote": ready_count,
        "categories": categories,
    }


@router.get("/v1/calibration/{tenant}/history", tags=["Control Plane"])
async def get_calibration_history(tenant: str):
    """Full promotion/rollback audit trail for all shadow categories of a tenant."""
    from aion.nemos import get_nemos
    nemos = get_nemos()
    history = await nemos.get_all_promotion_history(tenant)
    return {
        "tenant": tenant,
        "total_categories_with_history": len(history),
        "history": history,
    }


@router.post("/v1/calibration/{tenant}/promote", tags=["Control Plane"])
async def promote_shadow_category(tenant: str, request: Request):
    """Promote a shadow category to enforcement for a tenant."""
    from aion.config import get_estixe_settings
    from aion.nemos import get_nemos

    def _error_response(status: int, message: str, code: str, error_type: str = "api_error") -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"error": {"message": message, "type": error_type, "code": code}},
        )

    try:
        body = await request.json()
    except Exception:
        return _error_response(400, "Invalid JSON body", "invalid_json", "invalid_request")

    category = body.get("category")
    if not category:
        return _error_response(400, "Missing required field: category", "missing_field", "invalid_request")

    estixe_cfg = get_estixe_settings()
    nemos = get_nemos()
    obs = await nemos._load_shadow_observation(tenant, category)

    if obs.total_seen == 0:
        return _error_response(
            404,
            f"No shadow observations found for category '{category}' in tenant '{tenant}'",
            "not_found",
            "invalid_request",
        )

    if obs.promoted:
        return _error_response(
            409,
            f"Category '{category}' is already promoted for tenant '{tenant}'",
            "already_promoted",
            "invalid_request",
        )

    force = bool(body.get("force", False))
    gates_failed = []

    min_requests = estixe_cfg.shadow_promote_min_requests
    min_days = estixe_cfg.shadow_promote_min_days
    if not obs.is_promotion_ready(min_requests, min_days):
        gates_failed.append({
            "gate": "volume_and_time",
            "reason": (
                f"Need {min_requests} requests (have {obs.total_seen}) "
                f"and {min_days} days (have {round(obs.days_monitored, 1)})"
            ),
        })

    max_std = estixe_cfg.shadow_promote_min_stability
    if not obs.is_stable_enough(max_std):
        gates_failed.append({
            "gate": "stability",
            "reason": (
                f"confidence_std={round(obs.confidence_std, 4)} exceeds max={max_std} "
                f"(stability_score={round(obs.stability_score, 3)}). "
                f"Signal needs more consistent observations."
            ),
        })

    if gates_failed and not force:
        return JSONResponse(
            status_code=422,
            content={
                "error": "promotion_criteria_not_met",
                "message": "Use force=true to bypass volume/stability gates (drift and cooldown still apply).",
                "gates_failed": gates_failed,
                "observations": obs.to_dict(),
            },
        )

    cooldown_days = estixe_cfg.shadow_promote_cooldown_days
    cooldown_remaining = obs.cooldown_remaining_days(cooldown_days)
    if cooldown_remaining > 0:
        return JSONResponse(
            status_code=429,
            content={
                "error": "promotion_cooldown_active",
                "message": (
                    f"Category '{category}' was promoted recently. "
                    f"Cooldown: {round(cooldown_remaining, 1)} days remaining."
                ),
                "cooldown_days": cooldown_days,
                "remaining_days": round(cooldown_remaining, 1),
            },
        )

    threshold = body.get("threshold")
    threshold = round(float(threshold), 3) if threshold is not None else obs.suggested_threshold()

    existing_overrides = await get_overrides(tenant)
    existing_thresholds: dict = existing_overrides.get("estixe_thresholds") or {}
    current_threshold = existing_thresholds.get(category)
    max_delta = estixe_cfg.shadow_promote_max_threshold_delta
    if current_threshold is not None:
        delta = abs(threshold - current_threshold)
        if delta > max_delta:
            clamped = round(current_threshold + (max_delta if threshold > current_threshold else -max_delta), 3)
            return JSONResponse(
                status_code=422,
                content={
                    "error": "threshold_drift_exceeded",
                    "message": (
                        f"Requested threshold {threshold} deviates {round(delta, 3)} from "
                        f"current {current_threshold} (max_delta={max_delta}). "
                        f"Suggested safe value: {clamped}"
                    ),
                    "current_threshold": current_threshold,
                    "requested_threshold": threshold,
                    "max_delta": max_delta,
                    "suggested_threshold": clamped,
                },
            )

    existing_thresholds[category] = threshold
    await set_override("estixe_thresholds", existing_thresholds, tenant)

    await nemos.mark_shadow_promoted(tenant, category, previous_threshold=current_threshold)

    history_event = {
        "event": "promote",
        "timestamp": time.time(),
        "threshold_before": current_threshold,
        "threshold_after": threshold,
        "observations_count": obs.total_seen,
        "days_monitored": round(obs.days_monitored, 2),
        "avg_confidence": round(obs.avg_confidence, 4),
        "confidence_std": round(obs.confidence_std, 4),
        "stability_score": round(obs.stability_score, 3),
        "force": force,
        "gates_bypassed": [g["gate"] for g in gates_failed] if force else [],
    }
    await nemos.record_promotion_event(tenant, category, history_event)

    logger.info(
        "SHADOW PROMOTED: tenant='%s' category='%s' threshold=%.3f "
        "(prev=%.3f force=%s std=%.4f stability=%.3f n=%d)",
        tenant, category, threshold,
        current_threshold or 0.0, force,
        obs.confidence_std, obs.stability_score, obs.total_seen,
    )

    return {
        "status": "promoted",
        "tenant": tenant,
        "category": category,
        "threshold_before": current_threshold,
        "threshold_applied": threshold,
        "effect": "immediate — threshold override active via estixe_thresholds",
        "rollback_available": True,
        "persist_note": (
            f"To make permanent, set 'threshold: {threshold}' and remove 'shadow: true' "
            f"from '{category}' in risk_taxonomy.yaml, then POST /v1/estixe/intents/reload"
        ),
        "signal_quality": {
            "observations": obs.total_seen,
            "days_monitored": round(obs.days_monitored, 2),
            "avg_confidence": round(obs.avg_confidence, 4),
            "confidence_std": round(obs.confidence_std, 4),
            "stability_score": round(obs.stability_score, 3),
        },
        "gates_bypassed": history_event["gates_bypassed"],
    }


@router.post("/v1/calibration/{tenant}/rollback", tags=["Control Plane"])
async def rollback_shadow_category(tenant: str, request: Request):
    """Roll back a promoted shadow category to its pre-promotion threshold."""
    from aion.nemos import get_nemos

    def _error_response(status: int, message: str, code: str, error_type: str = "api_error") -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"error": {"message": message, "type": error_type, "code": code}},
        )

    try:
        body = await request.json()
    except Exception:
        return _error_response(400, "Invalid JSON body", "invalid_json", "invalid_request")

    category = body.get("category")
    if not category:
        return _error_response(400, "Missing required field: category", "missing_field", "invalid_request")

    nemos = get_nemos()
    obs = await nemos._load_shadow_observation(tenant, category)

    if not obs.promoted:
        return _error_response(
            409,
            f"Category '{category}' is not currently promoted for tenant '{tenant}'",
            "not_promoted",
            "invalid_request",
        )

    previous_threshold = obs.previous_threshold
    existing_overrides = await get_overrides(tenant)
    existing_thresholds: dict = existing_overrides.get("estixe_thresholds") or {}
    current_threshold = existing_thresholds.get(category)

    if previous_threshold is not None:
        existing_thresholds[category] = previous_threshold
    else:
        existing_thresholds.pop(category, None)
    await set_override("estixe_thresholds", existing_thresholds, tenant)

    await nemos.mark_shadow_rolled_back(tenant, category)

    history_event = {
        "event": "rollback",
        "timestamp": time.time(),
        "threshold_before": current_threshold,
        "threshold_after": previous_threshold,
        "reason": body.get("reason", "manual_rollback"),
    }
    await nemos.record_promotion_event(tenant, category, history_event)

    logger.info(
        "SHADOW ROLLBACK: tenant='%s' category='%s' threshold %.3f → %s",
        tenant, category, current_threshold or 0.0,
        f"{previous_threshold:.3f}" if previous_threshold is not None else "taxonomy_default",
    )

    return {
        "status": "rolled_back",
        "tenant": tenant,
        "category": category,
        "threshold_restored": previous_threshold,
        "effect": (
            "taxonomy default threshold restored"
            if previous_threshold is None
            else f"threshold reverted to {previous_threshold}"
        ),
        "note": "Category is back in shadow mode — observations continue accumulating.",
    }


@router.get("/v1/estixe/suggestions", tags=["Control Plane"])
async def list_suggestions(request: Request):
    """List auto-discovered bypass intent suggestions for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    try:
        from aion.estixe.suggestions import get_suggestion_engine
        engine = get_suggestion_engine()
        suggestions = engine.generate(tenant)
        return {
            "tenant": tenant,
            "total_samples": engine.tenant_sample_count(tenant),
            "suggestions": [s.to_dict() for s in suggestions],
            "count": len(suggestions),
        }
    except Exception as exc:
        logger.warning("Suggestion generation failed: %s", exc)
        return {"tenant": tenant, "total_samples": 0, "suggestions": [], "count": 0}


@router.post("/v1/estixe/suggestions/{suggestion_id}/approve", tags=["Control Plane"])
async def approve_suggestion(suggestion_id: str, request: Request):
    """Approve a suggestion — marks it for intent creation."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    def _error_response(status: int, message: str, code: str, error_type: str = "api_error") -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"error": {"message": message, "type": error_type, "code": code}},
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    from aion.estixe.suggestions import get_suggestion_engine
    engine = get_suggestion_engine()
    existing = next((s for s in engine.generate(tenant) if s.id == suggestion_id), None)
    if not existing:
        return _error_response(404, f"Suggestion '{suggestion_id}' not found", "not_found", "invalid_request")

    intent_name = body.get("intent_name", existing.suggested_intent_name)
    response_text = body.get("response", existing.suggested_response)

    if not engine.approve(tenant, suggestion_id):
        return _error_response(404, f"Suggestion '{suggestion_id}' not found", "not_found", "invalid_request")

    examples_yaml = "\n".join(f'      - "{msg}"' for msg in existing.sample_messages)
    yaml_snippet = (
        f"{intent_name}:\n"
        f"    action: bypass\n"
        f"    examples:\n{examples_yaml}\n"
        f"    responses:\n"
        f'      - "{response_text}"'
    )

    return {
        "status": "approved",
        "suggestion_id": suggestion_id,
        "intent_name": intent_name,
        "response": response_text,
        "yaml_snippet": yaml_snippet,
        "note": "Adicione este bloco ao config/intents.yaml e chame /v1/estixe/intents/reload",
    }


@router.post("/v1/estixe/suggestions/{suggestion_id}/reject", tags=["Control Plane"])
async def reject_suggestion(suggestion_id: str, request: Request):
    """Reject a suggestion so it doesn't resurface."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    from aion.estixe.suggestions import get_suggestion_engine
    get_suggestion_engine().reject(tenant, suggestion_id)
    return {"status": "rejected", "suggestion_id": suggestion_id}


@router.post("/v1/estixe/intents/reload", tags=["Control Plane"])
async def reload_intents():
    """Reload intents.yaml AND risk_taxonomy.yaml without restart."""
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            summary = await module.reload()
            return {"status": "reloaded", **summary}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@router.post("/v1/estixe/policies/reload", tags=["Control Plane"])
async def reload_policies():
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._policy.reload()
            return {"status": "reloaded", "rules": module._policy.rule_count}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@router.post("/v1/estixe/guardrails/reload", tags=["Control Plane"])
async def reload_guardrails():
    """Hot-reload regex PII patterns sem restart."""
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            return module._guardrails.reload()
    raise HTTPException(status_code=404, detail="ESTIXE not active")
