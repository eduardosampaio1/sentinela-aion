"""Approvals router: /v1/approvals."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("aion")

router = APIRouter()


def _error_response(status: int, message: str, code: str, error_type: str = "api_error") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


@router.get("/v1/approvals/{approval_id}", tags=["Control Plane"])
async def get_approval(approval_id: str):
    """Polling endpoint — returns the current status of a human-approval request."""
    from aion.adapter.approval_executor import _approval_key
    from aion.nemos import get_nemos
    record = await get_nemos()._store.get_json(_approval_key(approval_id))
    if not record:
        return _error_response(404, f"Approval '{approval_id}' not found", "not_found", "invalid_request")
    return record


@router.post("/v1/approvals/{approval_id}/resolve", tags=["Control Plane"])
async def resolve_approval(approval_id: str, request: Request):
    """Resolve a pending approval (approved or denied).

    Body: ``{"status": "approved|denied", "approver": "string"}``
    """
    import time as _time
    from aion.adapter.approval_executor import _approval_key
    from aion.nemos import get_nemos

    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("approved", "denied"):
        return _error_response(400, "status must be 'approved' or 'denied'", "invalid_status", "invalid_request")
    approver = body.get("approver", "unknown")

    nemos = get_nemos()
    key = _approval_key(approval_id)
    record = await nemos._store.get_json(key)
    if not record:
        return _error_response(404, f"Approval '{approval_id}' not found", "not_found", "invalid_request")
    if record.get("status") != "pending":
        return _error_response(
            409, f"Approval already resolved (status={record['status']})",
            "already_resolved", "invalid_request",
        )

    record["status"] = new_status
    record["resolved_by"] = approver
    record["resolved_at"] = _time.time()
    await nemos._store.set_json(key, record, ttl_seconds=7 * 86400)
    return {"approval_request_id": approval_id, "status": new_status, "resolved_by": approver}


@router.get("/v1/approvals", tags=["Control Plane"])
async def list_approvals(
    tenant: str | None = None, status: str | None = "pending", limit: int = 50,
):
    """List approvals filtered by tenant and status."""
    from aion.nemos import get_nemos
    nemos = get_nemos()
    keys = await nemos._store.keys_by_prefix("aion:approval:")
    items = []
    for key in keys:
        rec = await nemos._store.get_json(key)
        if not rec:
            continue
        if tenant and rec.get("tenant") != tenant:
            continue
        if status and rec.get("status") != status:
            continue
        items.append(rec)
        if len(items) >= limit:
            break
    return {"approvals": items, "count": len(items)}
