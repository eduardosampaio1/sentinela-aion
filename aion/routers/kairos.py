"""KAIROS router — Policy Lifecycle Manager endpoints.

Endpoints:
    GET  /v1/kairos/templates                    → list available policy templates
    POST /v1/kairos/candidates/from-template     → instantiate PolicyCandidate from template
    GET  /v1/kairos/candidates                   → list candidates (query: status, type)
    GET  /v1/kairos/candidates/{id}              → detail + lifecycle events + shadow run
    POST /v1/kairos/candidates/{id}/shadow       → start shadow run
    POST /v1/kairos/candidates/{id}/approve      → approve for production
    POST /v1/kairos/candidates/{id}/reject       → reject candidate

Headers:
    X-Aion-Tenant-Id  — required on all endpoints
    X-Aion-Actor-Id   — required on approve / reject; optional on shadow (audit trail)

Error semantics:
    503 — KAIROS module is disabled (KAIROS_ENABLED=false)
    409 — invalid state machine transition
    404 — resource not found
    400 — missing / invalid input
    500 — unexpected internal error

Note on store errors: KairosStore backends are fire-and-forget by design — they log
and swallow IO errors to avoid blocking the governance workflow. Do NOT expect 503 for
store IO failures; those are logged at ERROR level by the store itself.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from aion.kairos import get_kairos
from aion.kairos.models import (
    LifecycleActorType,
    LifecycleEvent,
    PolicyCandidate,
    PolicyCandidateStatus,
)
from aion.kairos.templates import load_templates

logger = logging.getLogger("aion.kairos.router")

router = APIRouter()

_TAG = "KAIROS"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _err(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": "api_error", "code": code}},
    )


def _tenant(request: Request) -> Optional[str]:
    return request.headers.get("X-Aion-Tenant-Id")


def _actor(request: Request) -> Optional[str]:
    return request.headers.get("X-Aion-Actor-Id")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_body(request: Request) -> dict:
    """Parse JSON body, returning empty dict on missing or malformed body."""
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _check_tenant_ownership(candidate: PolicyCandidate, tenant_id: str) -> bool:
    """Defense-in-depth: verify candidate belongs to the requesting tenant."""
    return candidate.tenant_id == tenant_id


# ── GET /v1/kairos/templates ───────────────────────────────────────────────────


@router.get("/v1/kairos/templates", tags=[_TAG])
async def list_templates():
    """List all available policy templates."""
    templates = load_templates()
    return {
        "templates": [t.model_dump() for t in templates],
        "count": len(templates),
    }


# ── POST /v1/kairos/candidates/from-template ─────────────────────────────────


@router.post("/v1/kairos/candidates/from-template", tags=[_TAG])
async def create_candidate_from_template(request: Request):
    """Instantiate a PolicyCandidate from a template.

    Body (JSON):
        template_id      str  — required
        title            str  — optional, overrides template title
        business_summary str  — optional
    """
    tenant_id = _tenant(request)
    if not tenant_id:
        return _err(400, "X-Aion-Tenant-Id header is required", "missing_tenant")

    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
    except Exception:
        return _err(400, "Invalid JSON body", "invalid_body")

    template_id = (body.get("template_id") or "").strip()
    if not template_id:
        return _err(400, "template_id is required", "missing_template_id")

    templates = {t.id: t for t in load_templates()}
    template = templates.get(template_id)
    if template is None:
        return _err(404, f"Template '{template_id}' not found", "template_not_found")

    try:
        kairos = get_kairos()
    except RuntimeError as exc:
        logger.error("KAIROS: module unavailable: %s", exc)
        return _err(503, "KAIROS module is unavailable (check KAIROS_ENABLED)", "kairos_unavailable")

    now = _now_iso()
    candidate = PolicyCandidate(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        template_id=template_id,
        type=template.type,
        status=PolicyCandidateStatus.DRAFT,
        title=body.get("title") or template.title,
        business_summary=body.get("business_summary") or template.description,
        technical_summary=body.get("technical_summary") or "",
        created_at=now,
        updated_at=now,
    )

    try:
        await kairos.store.save_candidate(candidate)
    except Exception:
        logger.exception("KAIROS: failed to save candidate from template %s", template_id)
        return _err(500, "Failed to create candidate", "internal_error")

    # Save initial lifecycle event — non-critical: failure is logged but does not fail the request.
    try:
        event = LifecycleEvent(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            tenant_id=tenant_id,
            from_status=None,
            to_status=PolicyCandidateStatus.DRAFT.value,
            actor_type=LifecycleActorType.SYSTEM,
            actor_id=None,
            reason="created_from_template",
            metadata={"template_id": template_id},
            created_at=now,
        )
        await kairos.store.save_lifecycle_event(event)
    except Exception:
        logger.warning("KAIROS: failed to save initial lifecycle event for candidate %s", candidate.id)

    return JSONResponse(status_code=201, content=candidate.model_dump())


# ── GET /v1/kairos/candidates ─────────────────────────────────────────────────


@router.get("/v1/kairos/candidates", tags=[_TAG])
async def list_candidates(
    request: Request,
    status: Optional[str] = None,
    type: Optional[str] = None,
):
    """List PolicyCandidates for the tenant.

    Query params:
        status  — filter by status (e.g. draft, shadow_running)
        type    — filter by policy type (e.g. bypass, guardrail)
    """
    tenant_id = _tenant(request)
    if not tenant_id:
        return _err(400, "X-Aion-Tenant-Id header is required", "missing_tenant")

    try:
        kairos = get_kairos()
    except RuntimeError as exc:
        logger.error("KAIROS: module unavailable: %s", exc)
        return _err(503, "KAIROS module is unavailable", "kairos_unavailable")

    try:
        candidates = await kairos.store.list_candidates(tenant_id, status=status, policy_type=type)
    except Exception:
        logger.exception("KAIROS: failed to list candidates for tenant %s", tenant_id)
        return _err(500, "Failed to list candidates", "internal_error")

    return {
        "candidates": [c.model_dump() for c in candidates],
        "count": len(candidates),
    }


# ── GET /v1/kairos/candidates/{id} ────────────────────────────────────────────


@router.get("/v1/kairos/candidates/{candidate_id}", tags=[_TAG])
async def get_candidate(candidate_id: str, request: Request):
    """Get a PolicyCandidate with its lifecycle events and active shadow run."""
    tenant_id = _tenant(request)
    if not tenant_id:
        return _err(400, "X-Aion-Tenant-Id header is required", "missing_tenant")

    try:
        kairos = get_kairos()
    except RuntimeError as exc:
        logger.error("KAIROS: module unavailable: %s", exc)
        return _err(503, "KAIROS module is unavailable", "kairos_unavailable")

    try:
        candidate = await kairos.store.get_candidate(tenant_id, candidate_id)
    except Exception:
        logger.exception("KAIROS: failed to get candidate %s", candidate_id)
        return _err(500, "Failed to get candidate", "internal_error")

    if candidate is None:
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    # Defense-in-depth: tenant ownership check (store already filters by tenant_id)
    if not _check_tenant_ownership(candidate, tenant_id):
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    try:
        events = await kairos.store.get_lifecycle_events(candidate_id)
        shadow_run = None
        if candidate.shadow_run_id:
            shadow_run = await kairos.store.get_shadow_run(candidate.shadow_run_id)
    except Exception:
        logger.exception("KAIROS: failed to load detail for candidate %s", candidate_id)
        return _err(500, "Failed to get candidate detail", "internal_error")

    return {
        "candidate": candidate.model_dump(),
        "lifecycle_events": [e.model_dump() for e in events],
        "shadow_run": shadow_run.model_dump() if shadow_run else None,
    }


# ── POST /v1/kairos/candidates/{id}/ready ────────────────────────────────────


@router.post("/v1/kairos/candidates/{candidate_id}/ready", tags=[_TAG])
async def mark_ready_for_shadow(candidate_id: str, request: Request):
    """Transition a draft PolicyCandidate to ready_for_shadow.

    Candidate must be in draft status. Signals that the policy has been reviewed
    and is ready to enter shadow observation.
    """
    tenant_id = _tenant(request)
    if not tenant_id:
        return _err(400, "X-Aion-Tenant-Id header is required", "missing_tenant")

    actor_id = _actor(request)

    try:
        kairos = get_kairos()
    except RuntimeError as exc:
        logger.error("KAIROS: module unavailable: %s", exc)
        return _err(503, "KAIROS module is unavailable", "kairos_unavailable")

    try:
        candidate = await kairos.store.get_candidate(tenant_id, candidate_id)
    except Exception:
        logger.exception("KAIROS: failed to get candidate %s for ready transition", candidate_id)
        return _err(500, "Failed to retrieve candidate", "internal_error")

    if candidate is None:
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    if not _check_tenant_ownership(candidate, tenant_id):
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    try:
        candidate = await kairos.lifecycle_manager.transition(
            candidate,
            PolicyCandidateStatus.READY_FOR_SHADOW,
            actor_type=LifecycleActorType.OPERATOR,
            actor_id=actor_id,
            reason="marked_ready_for_shadow",
        )
    except ValueError as exc:
        return _err(409, str(exc), "invalid_transition")
    except Exception:
        logger.exception("KAIROS: failed to mark candidate %s ready for shadow", candidate_id)
        return _err(500, "Failed to transition candidate", "internal_error")

    return candidate.model_dump()


# ── POST /v1/kairos/candidates/{id}/shadow ────────────────────────────────────


@router.post("/v1/kairos/candidates/{candidate_id}/shadow", tags=[_TAG])
async def start_shadow(candidate_id: str, request: Request):
    """Start a shadow run for a PolicyCandidate.

    Candidate must be in ready_for_shadow status.
    X-Aion-Actor-Id is optional but recommended for audit trail.
    """
    tenant_id = _tenant(request)
    if not tenant_id:
        return _err(400, "X-Aion-Tenant-Id header is required", "missing_tenant")

    actor_id = _actor(request)

    try:
        kairos = get_kairos()
    except RuntimeError as exc:
        logger.error("KAIROS: module unavailable: %s", exc)
        return _err(503, "KAIROS module is unavailable", "kairos_unavailable")

    try:
        candidate = await kairos.store.get_candidate(tenant_id, candidate_id)
    except Exception:
        logger.exception("KAIROS: failed to get candidate %s for shadow", candidate_id)
        return _err(500, "Failed to retrieve candidate", "internal_error")

    if candidate is None:
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    if not _check_tenant_ownership(candidate, tenant_id):
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    try:
        candidate, run = await kairos.lifecycle_manager.start_shadow(candidate, actor_id=actor_id)
    except ValueError as exc:
        return _err(409, str(exc), "invalid_transition")
    except Exception:
        logger.exception("KAIROS: failed to start shadow for candidate %s", candidate_id)
        return _err(500, "Failed to start shadow run", "internal_error")

    return {
        "candidate": candidate.model_dump(),
        "shadow_run": run.model_dump(),
    }


# ── POST /v1/kairos/candidates/{id}/approve ──────────────────────────────────


@router.post("/v1/kairos/candidates/{candidate_id}/approve", tags=[_TAG])
async def approve_candidate(candidate_id: str, request: Request):
    """Approve a PolicyCandidate for production.

    Candidate must be in shadow_completed status.
    Requires X-Aion-Actor-Id header.

    Body (JSON, optional):
        reason  str  — approval reason or justification
    """
    tenant_id = _tenant(request)
    if not tenant_id:
        return _err(400, "X-Aion-Tenant-Id header is required", "missing_tenant")

    actor_id = _actor(request)
    if not actor_id:
        return _err(400, "X-Aion-Actor-Id header is required for approval", "missing_actor")

    body = await _get_body(request)
    reason: Optional[str] = body.get("reason") or None

    try:
        kairos = get_kairos()
    except RuntimeError as exc:
        logger.error("KAIROS: module unavailable: %s", exc)
        return _err(503, "KAIROS module is unavailable", "kairos_unavailable")

    try:
        candidate = await kairos.store.get_candidate(tenant_id, candidate_id)
    except Exception:
        logger.exception("KAIROS: failed to get candidate %s for approve", candidate_id)
        return _err(500, "Failed to retrieve candidate", "internal_error")

    if candidate is None:
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    if not _check_tenant_ownership(candidate, tenant_id):
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    try:
        candidate = await kairos.lifecycle_manager.approve(candidate, actor_id=actor_id, reason=reason)
    except ValueError as exc:
        return _err(409, str(exc), "invalid_transition")
    except Exception:
        logger.exception("KAIROS: failed to approve candidate %s", candidate_id)
        return _err(500, "Failed to approve candidate", "internal_error")

    return candidate.model_dump()


# ── POST /v1/kairos/candidates/{id}/reject ────────────────────────────────────


@router.post("/v1/kairos/candidates/{candidate_id}/reject", tags=[_TAG])
async def reject_candidate(candidate_id: str, request: Request):
    """Reject a PolicyCandidate.

    Candidate must be in shadow_completed or under_review status.
    Requires X-Aion-Actor-Id header and reason in body.

    Body (JSON):
        reason  str  — required rejection justification
    """
    tenant_id = _tenant(request)
    if not tenant_id:
        return _err(400, "X-Aion-Tenant-Id header is required", "missing_tenant")

    actor_id = _actor(request)
    if not actor_id:
        return _err(400, "X-Aion-Actor-Id header is required for rejection", "missing_actor")

    body = await _get_body(request)
    reason = (body.get("reason") or "").strip()
    if not reason:
        return _err(400, "reason is required in body for rejection", "missing_reason")

    try:
        kairos = get_kairos()
    except RuntimeError as exc:
        logger.error("KAIROS: module unavailable: %s", exc)
        return _err(503, "KAIROS module is unavailable", "kairos_unavailable")

    try:
        candidate = await kairos.store.get_candidate(tenant_id, candidate_id)
    except Exception:
        logger.exception("KAIROS: failed to get candidate %s for reject", candidate_id)
        return _err(500, "Failed to retrieve candidate", "internal_error")

    if candidate is None:
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    if not _check_tenant_ownership(candidate, tenant_id):
        return _err(404, f"Candidate '{candidate_id}' not found", "not_found")

    try:
        candidate = await kairos.lifecycle_manager.reject(candidate, actor_id=actor_id, reason=reason)
    except ValueError as exc:
        return _err(409, str(exc), "invalid_transition")
    except Exception:
        logger.exception("KAIROS: failed to reject candidate %s", candidate_id)
        return _err(500, "Failed to reject candidate", "internal_error")

    return candidate.model_dump()
