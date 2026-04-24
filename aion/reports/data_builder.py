"""Report data builder — aggregates all NEMOS + audit data into a report structure."""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("aion.reports.data_builder")


async def _redis():
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0)
        await r.ping()
        return r
    except Exception:
        return None


async def build_report_data(tenant: str, period_days: int = 30) -> dict[str, Any]:
    """Aggregate all available data for `tenant` over the last `period_days` days.

    All Redis operations are best-effort — missing data returns zero/empty.
    """
    import json

    r = await _redis()
    today = datetime.date.today()

    # ── Economics ──────────────────────────────────────────────────────────
    total_actual_cost = 0.0
    total_saved = 0.0
    model_distribution: dict[str, int] = {}
    days_with_data = 0

    for delta in range(period_days):
        date_str = (today - datetime.timedelta(days=delta)).isoformat()
        if r:
            try:
                raw = await r.get(f"aion:econ:{tenant}:daily:{date_str}")
                if raw:
                    bucket = json.loads(raw)
                    total_actual_cost += bucket.get("total_actual_cost", 0.0)
                    total_saved += bucket.get("total_savings", 0.0)
                    days_with_data += 1
                    for model, count in bucket.get("requests_by_model", {}).items():
                        model_distribution[model] = model_distribution.get(model, 0) + count
            except Exception:
                pass

    # ── Security ───────────────────────────────────────────────────────────
    requests_blocked = 0
    pii_intercepted = 0

    try:
        from aion.shared.telemetry import get_counters
        counters = get_counters()
        requests_blocked = counters.get("blocked_total", 0)
        pii_intercepted = counters.get("pii_violations_total", 0)
    except Exception:
        pass

    # ── Session audit ──────────────────────────────────────────────────────
    session_count = 0
    verified_sessions = 0

    if r:
        try:
            # Count sessions via ZSET index
            zset_key = f"aion:session_index:{tenant}"
            session_count = await r.zcard(zset_key) or 0
            # Spot-check verification for first 20 sessions
            members = await r.zrange(zset_key, 0, 19)
            for sid in members:
                raw = await r.get(f"aion:session_audit:{tenant}:{sid}")
                if raw:
                    try:
                        rec_data = json.loads(raw)
                        sig = rec_data.get("hmac_signature", "")
                        if sig.startswith("kid:"):
                            verified_sessions += 1
                    except Exception:
                        pass
        except Exception:
            pass

    # ── Intelligence ───────────────────────────────────────────────────────
    intent_memory: list[dict] = []
    model_performance: list[dict] = []

    if r:
        try:
            import re as _re
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor, match=f"aion:estixe:{tenant}:intent:*", count=50)
                for key in keys:
                    raw = await r.get(key)
                    if raw:
                        data = json.loads(raw)
                        intent_name = _re.sub(rf"aion:estixe:{tenant}:intent:", "", key)
                        intent_memory.append({
                            "intent": intent_name,
                            "bypass_success_rate": data.get("bypass_success_rate", 0.0),
                            "followup_rate": data.get("followup_rate", 0.0),
                            "sample_count": data.get("sample_count", 0),
                        })
                if cursor == 0:
                    break
            intent_memory = sorted(intent_memory, key=lambda x: x["sample_count"], reverse=True)[:20]
        except Exception:
            pass

        try:
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor, match=f"aion:memory:{tenant}:*", count=50)
                for key in keys:
                    raw = await r.get(key)
                    if raw:
                        data = json.loads(raw)
                        model_name = key.split(":")[-1]
                        model_performance.append({
                            "model": model_name,
                            "success_rate": data.get("success_rate", 0.0),
                            "avg_latency_ms": data.get("avg_latency_ms", 0.0),
                            "avg_cost": data.get("avg_cost", 0.0),
                            "request_count": data.get("request_count", 0),
                        })
                if cursor == 0:
                    break
        except Exception:
            pass

    # ── Compression (METIS) ────────────────────────────────────────────────
    tokens_saved = 0
    compression_ratio = 0.0

    if r:
        try:
            raw = await r.get(f"aion:metis:{tenant}:optimization")
            if raw:
                opt = json.loads(raw)
                tokens_saved = opt.get("tokens_saved", 0)
                compression_ratio = opt.get("compression_effectiveness", 0.0)
        except Exception:
            pass

    # ── Budget ─────────────────────────────────────────────────────────────
    budget_config: dict = {}
    today_spend = 0.0

    try:
        from aion.shared.budget import get_budget_store
        store = get_budget_store()
        config = await store.get_config(tenant)
        if config:
            budget_config = config.model_dump()
        state = await store.get_state(tenant)
        today_spend = state.today_spend
    except Exception:
        pass

    return {
        "tenant": tenant,
        "period_days": period_days,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "economics": {
            "total_cost_usd": round(total_actual_cost, 4),
            "total_saved_usd": round(total_saved, 4),
            "days_with_data": days_with_data,
            "model_distribution": model_distribution,
        },
        "security": {
            "requests_blocked": requests_blocked,
            "pii_intercepted": pii_intercepted,
        },
        "sessions": {
            "total": int(session_count),
            "verified": verified_sessions,
            "verification_rate": round(verified_sessions / max(session_count, 1), 3),
        },
        "intelligence": {
            "top_intents": intent_memory,
            "model_performance": model_performance,
            "tokens_saved": tokens_saved,
            "compression_ratio": round(compression_ratio, 3),
        },
        "budget": {
            "today_spend_usd": round(today_spend, 4),
            "config": budget_config,
        },
    }
