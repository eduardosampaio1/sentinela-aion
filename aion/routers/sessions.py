"""Sessions router: /v1/sessions, /v1/session audit."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from aion.config import get_settings

logger = logging.getLogger("aion")

router = APIRouter()


@router.get("/v1/sessions/{tenant_id}", tags=["Observability"])
async def list_sessions(tenant_id: str, page: int = 1, limit: int = 20):
    """List recent sessions for a tenant (paginated, most recent first)."""
    from aion.shared.session_audit import get_session_audit_store
    limit = min(max(1, limit), 100)
    sessions = await get_session_audit_store().list_sessions(tenant_id, page=page, limit=limit)
    return {"tenant": tenant_id, "page": page, "sessions": sessions}


@router.get("/v1/session/{session_id}/audit", tags=["Observability"])
async def get_session_audit(session_id: str, request: Request):
    """Full session audit trail with HMAC integrity signature."""
    from aion.shared.session_audit import get_session_audit_store
    from datetime import datetime, timezone
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    rec = await get_session_audit_store().get_session(tenant, session_id)
    if rec is None:
        return JSONResponse(
            status_code=404,
            content={"session_id": session_id, "found": False, "message": "Session not found"},
        )
    verified = rec.verify()

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None

    turns_out = []
    for t in rec.turns:
        d = t.model_dump()
        d["timestamp_iso"] = _iso(t.timestamp)
        turns_out.append(d)

    return {
        "session_id": rec.session_id,
        "tenant": rec.tenant,
        "turns_count": len(rec.turns),
        "started_at": rec.started_at,
        "started_at_iso": _iso(rec.started_at),
        "last_activity": rec.last_activity,
        "last_activity_iso": _iso(rec.last_activity),
        "hmac_signature": rec.hmac_signature,
        "verified": verified,
        "turns": turns_out,
    }


@router.get("/v1/session/{session_id}/audit/export", tags=["Observability"])
async def export_session_audit(session_id: str, request: Request, format: str = "json"):
    """Export session audit trail.

    format=json  → full JSON (default)
    format=csv   → CSV suitable for compliance spreadsheet import
    """
    from aion.shared.session_audit import get_session_audit_store
    from datetime import datetime, timezone
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    rec = await get_session_audit_store().get_session(tenant, session_id)
    if rec is None:
        return JSONResponse(
            status_code=404,
            content={"session_id": session_id, "found": False, "message": "Session not found"},
        )
    verified = rec.verify()

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""

    if format.lower() == "csv":
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "request_id", "timestamp_iso", "decision", "model_used",
            "risk_score", "intent_detected", "pii_types",
            "policies_matched", "tokens_sent", "tokens_received", "latency_ms",
        ])
        for t in rec.turns:
            writer.writerow([
                t.request_id, _iso(t.timestamp), t.decision,
                t.model_used or "", t.risk_score,
                t.intent_detected or "", "|".join(t.pii_types_detected),
                "|".join(t.policies_matched), t.tokens_sent,
                t.tokens_received, t.latency_ms,
            ])
        csv_content = buf.getvalue()
        headers = {
            "Content-Disposition": f'attachment; filename="session_{session_id}_audit.csv"',
            "X-Aion-Verified": str(verified).lower(),
        }
        return Response(content=csv_content, media_type="text/csv", headers=headers)

    turns_out = []
    for t in rec.turns:
        d = t.model_dump()
        d["timestamp_iso"] = _iso(t.timestamp)
        turns_out.append(d)

    return JSONResponse(content={
        "session_id": rec.session_id,
        "tenant": rec.tenant,
        "started_at_iso": _iso(rec.started_at),
        "last_activity_iso": _iso(rec.last_activity),
        "verified": verified,
        "hmac_signature": rec.hmac_signature,
        "turns_count": len(rec.turns),
        "turns": turns_out,
    }, headers={"X-Aion-Verified": str(verified).lower()})
