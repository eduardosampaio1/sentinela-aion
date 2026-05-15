"""Intelligence router: /v1/intelligence, /v1/threats."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from aion.config import get_settings
from aion.shared.budget import get_budget_store
from aion.shared.telemetry import get_counters, get_recent_events, get_stats

logger = logging.getLogger("aion")

router = APIRouter()


@router.get("/v1/intelligence/{tenant_id}/overview", tags=["Intelligence"])
async def intelligence_overview(tenant_id: str, days: int = 30):
    """Single-endpoint summary of AION's value for a tenant."""
    from aion.nemos import get_nemos

    nemos = get_nemos()
    counters = get_counters()
    stats_data = get_stats(tenant_id)

    total_requests = counters.get("requests_total", 0)
    bypasses = counters.get("bypass_total", 0)
    blocks = counters.get("block_total", 0)
    tokens_saved = counters.get("tokens_saved_total", 0)
    cost_saved = counters.get("cost_saved_total", 0.0)

    baseline = None
    maturity = {}
    estimated_without_aion = 0.0
    total_spend = 0.0
    try:
        baseline = await nemos.get_baseline(tenant_id)
        maturity = await nemos.get_module_maturity(tenant_id)
        econ = await nemos.get_economics(tenant_id)
        if econ:
            total_spend = float(econ.total_actual_cost)
            estimated_without_aion = float(econ.total_default_cost)
    except Exception:
        pass

    savings = max(0.0, estimated_without_aion - total_spend) if estimated_without_aion else cost_saved
    savings_pct = round(savings / estimated_without_aion * 100, 1) if estimated_without_aion > 0 else 0.0

    pii_intercepted = 0
    top_block_reason = None
    try:
        recent = get_recent_events(50)
        pii_intercepted = sum(
            1 for e in recent
            if (e.get("metadata") or {}).get("pii_violations")
        )
        block_reasons = [
            (e.get("metadata") or {}).get("block_reason") or (e.get("metadata") or {}).get("detected_risk_category")
            for e in recent
            if e.get("decision") == "block"
        ]
        block_reasons = [r for r in block_reasons if r]
        if block_reasons:
            from collections import Counter
            top_block_reason = Counter(block_reasons).most_common(1)[0][0]
    except Exception:
        pass

    budget_info: dict = {}
    try:
        store = get_budget_store()
        b_config = await store.get_config(tenant_id)
        today_spend = await store.get_today_spend(tenant_id)
        if b_config:
            budget_info = {
                "daily_cap": b_config.daily_cap,
                "today_spend": round(today_spend, 6),
                "cap_pct": round(today_spend / b_config.daily_cap, 3) if b_config.daily_cap else None,
                "alert_active": bool(
                    b_config.daily_cap
                    and today_spend >= b_config.daily_cap * b_config.alert_threshold
                ),
                "on_cap_reached": b_config.on_cap_reached,
            }
    except Exception:
        pass

    avg_latency = baseline.avg_latency_ms if baseline else counters.get("latency_p50_ms", 0)
    top_model = None
    try:
        if baseline:
            top_model = getattr(baseline, "top_model", None)
    except Exception:
        pass

    return {
        "tenant": tenant_id,
        "period_days": days,
        "security": {
            "requests_blocked": blocks,
            "pii_intercepted": pii_intercepted,
            "top_block_reason": top_block_reason,
        },
        "economics": {
            # F-08: never substitute cost_saved when total_spend is zero — they are
            # different metrics. Return 0.0 so dashboards show "no data" honestly.
            "total_spend_usd": round(total_spend, 4) if total_spend else 0.0,
            "estimated_without_aion_usd": round(estimated_without_aion, 4),
            "savings_usd": round(savings, 4),
            "savings_pct": savings_pct,
            "tokens_saved": tokens_saved,
            "top_model_used": top_model,
        },
        "intelligence": {
            "requests_processed": total_requests,
            "bypass_rate": round(bypasses / total_requests, 3) if total_requests else 0,
            "avg_latency_ms": round(avg_latency, 1),
            "module_maturity": maturity,
        },
        "budget": budget_info or None,
    }


@router.get("/v1/intelligence/{tenant_id}/compliance-summary", tags=["Intelligence"])
async def intelligence_compliance_summary(tenant_id: str, request: Request):
    """CISO-ready compliance summary."""
    import hashlib as _hashlib
    from datetime import datetime, timezone

    counters = get_counters()
    stats_data = get_stats(tenant_id)

    total = counters.get("requests_total", 0)
    blocks = counters.get("block_total", 0)
    bypasses = counters.get("bypass_total", 0)
    passthroughs = total - blocks - bypasses

    pii_by_category: dict[str, int] = {}
    try:
        recent = get_recent_events(200)
        for e in recent:
            violations = (e.get("metadata") or {}).get("pii_violations") or []
            for v in violations:
                cat = v if isinstance(v, str) else str(v)
                pii_by_category[cat] = pii_by_category.get(cat, 0) + 1
    except Exception:
        pass

    session_count = 0
    try:
        from aion.shared.session_audit import get_session_audit_store
        sessions = await get_session_audit_store().list_sessions(tenant_id, page=1, limit=1)
        session_count = len(sessions)
    except Exception:
        pass

    report_data = {
        "tenant": tenant_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_retention_policy": "messages_not_stored_hash_only",
        "decisions": {
            "total_requests": total,
            "blocked": blocks,
            "bypassed": bypasses,
            "passed_to_llm": max(0, passthroughs),
            "block_rate": round(blocks / total, 4) if total else 0,
        },
        "pii": {
            "total_intercepts": sum(pii_by_category.values()),
            "by_category": pii_by_category,
            "note": "PII content is never stored; only category labels are recorded.",
        },
        "session_audit": {
            "sessions_with_audit_trail": session_count,
            "audit_trail_signed": bool(os.environ.get("AION_SESSION_AUDIT_SECRET")),
            "audit_ttl_days": int(os.environ.get("AION_SESSION_AUDIT_TTL", 7_776_000)) // 86400,
            "export_endpoint": f"/v1/session/{{session_id}}/audit/export",
        },
        "infrastructure": {
            "multi_turn_context_enabled": os.environ.get("AION_MULTI_TURN_CONTEXT", "").lower() in ("true", "1"),
            "budget_cap_enabled": os.environ.get("AION_BUDGET_ENABLED", "").lower() in ("true", "1"),
            "data_residency": os.environ.get("AION_DATA_RESIDENCY", "not_configured"),
            "audit_hash_chaining": True,
        },
    }

    report_json = __import__("json").dumps(report_data, sort_keys=True)
    secret = os.environ.get("AION_SESSION_AUDIT_SECRET", "")
    report_signature = ""
    if secret:
        import hmac as _hmac
        report_signature = "kid:v1:" + _hmac.new(secret.encode(), report_json.encode(), _hashlib.sha256).hexdigest()

    report_data["report_signature"] = report_signature
    report_data["signature_covers"] = "all fields except report_signature itself"
    return report_data


@router.get("/v1/intelligence/{tenant_id}/intents", tags=["Intelligence"])
async def get_intent_performance(tenant_id: str, limit: int = 50):
    """Intent-level performance summary from NEMOS IntentMemory.

    Returns what NEMOS actually tracks per-intent:
      name, requests, bypassed/forwarded counts,
      bypass_success_rate, avg_cost_when_forwarded, followup_rate, confidence.

    NOTE: current_model / best_model / savings_day are NOT available per-intent
    in the current NEMOS schema — those are model-level metrics in ModelPerformance.
    """
    from aion.nemos import get_nemos

    limit = min(max(1, limit), 200)

    try:
        intent_memories = await get_nemos().get_intent_memory(tenant_id)
    except Exception as exc:
        logger.error("Failed to load intent memory for %s: %s", tenant_id, exc)
        return {"tenant": tenant_id, "count": 0, "intents": []}

    intents = []
    for name, mem in intent_memories.items():
        if mem.total_seen == 0:
            continue
        conf = mem.confidence
        intents.append({
            "name": name,
            "requests": mem.total_seen,
            "bypassed": mem.bypassed_count,
            "forwarded": mem.forwarded_count,
            "bypass_success_rate": round(mem.bypass_success_rate.value, 4),
            "avg_cost_when_forwarded": round(mem.avg_cost_when_forwarded.value, 6),
            "followup_rate": round(mem.followup_rate.value, 4),
            "confidence": conf.value if hasattr(conf, "value") else str(conf),
        })

    # Most frequent intents first
    intents.sort(key=lambda x: x["requests"], reverse=True)

    return {
        "tenant": tenant_id,
        "count": len(intents),
        "intents": intents[:limit],
    }


@router.get("/v1/threats/{tenant_id}", tags=["Security"])
async def list_threat_signals(tenant_id: str):
    """List active threat signals for a tenant (multi-turn attack patterns)."""
    try:
        from aion.estixe.threat_detector import get_threat_detector
        signals = await get_threat_detector().get_active(tenant_id)
        return {
            "tenant": tenant_id,
            "threats": [s.model_dump() for s in signals],
            "count": len(signals),
        }
    except Exception as exc:
        logger.error("Failed to retrieve threat signals for %s: %s", tenant_id, exc)
        return {"tenant": tenant_id, "threats": [], "count": 0, "error": str(exc)}
