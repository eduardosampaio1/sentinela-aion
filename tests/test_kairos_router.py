"""Unit tests for aion/routers/kairos.py — Fase 3: REST API.

Tests cover:
- GET /v1/kairos/templates
- POST /v1/kairos/candidates/from-template (happy path + validation + store error)
- GET /v1/kairos/candidates (list, filters, missing tenant)
- GET /v1/kairos/candidates/{id} (found, not found, with shadow run, tenant mismatch)
- POST /v1/kairos/candidates/{id}/shadow (happy path + invalid transition + not found)
- POST /v1/kairos/candidates/{id}/approve (happy path + missing actor + invalid transition)
- POST /v1/kairos/candidates/{id}/reject (happy path + missing reason + invalid transition)
- KAIROS disabled → 503 on all mutating endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aion.kairos.models import (
    LifecycleActorType,
    LifecycleEvent,
    PolicyCandidate,
    PolicyCandidateStatus,
    PolicyTemplate,
    ShadowRun,
    ShadowRunStatus,
)


# ── App fixture ───────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """FastAPI test client with KAIROS router only (no full AION boot)."""
    from fastapi import FastAPI
    from aion.routers.kairos import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate(status: PolicyCandidateStatus = PolicyCandidateStatus.DRAFT, **kwargs) -> PolicyCandidate:
    defaults = {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant-test",
        "type": "bypass",
        "status": status,
        "title": "Test policy",
        "business_summary": "For testing",
        "created_at": _now(),
        "updated_at": _now(),
    }
    defaults.update(kwargs)
    return PolicyCandidate(**defaults)


def _template(template_id: str = "test_tmpl") -> PolicyTemplate:
    return PolicyTemplate(
        id=template_id,
        vertical="financeiro",
        type="bypass",
        title="Test template",
        description="For testing",
        risk_level="low",
        trigger={"intent_pattern": "hello"},
        action={"type": "bypass_llm"},
        fallback={"type": "model_tier", "value": "customer_default_model"},
    )


def _shadow_run(candidate_id: str) -> ShadowRun:
    return ShadowRun(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        tenant_id="tenant-test",
        status=ShadowRunStatus.RUNNING,
        started_at=_now(),
    )


def _event(candidate_id: str) -> LifecycleEvent:
    return LifecycleEvent(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        tenant_id="tenant-test",
        from_status=None,
        to_status="draft",
        actor_type=LifecycleActorType.SYSTEM,
        reason="created_from_template",
        created_at=_now(),
    )


def _mock_kairos(
    candidates: list[PolicyCandidate] | None = None,
    candidate: PolicyCandidate | None = None,
    shadow_run: ShadowRun | None = None,
    events: list[LifecycleEvent] | None = None,
):
    store = MagicMock()
    store.save_candidate = AsyncMock()
    store.save_lifecycle_event = AsyncMock()
    store.save_shadow_run = AsyncMock()
    store.get_candidate = AsyncMock(return_value=candidate)
    store.list_candidates = AsyncMock(return_value=candidates or [])
    store.get_shadow_run = AsyncMock(return_value=shadow_run)
    store.get_lifecycle_events = AsyncMock(return_value=events or [])

    lifecycle_manager = MagicMock()
    lifecycle_manager.start_shadow = AsyncMock()
    lifecycle_manager.approve = AsyncMock()
    lifecycle_manager.reject = AsyncMock()

    kairos = MagicMock()
    kairos.store = store
    kairos.lifecycle_manager = lifecycle_manager
    return kairos


# ── GET /v1/kairos/templates ───────────────────────────────────────────────────


class TestListTemplates:
    def test_returns_templates(self, client):
        templates = [_template("tmpl_a"), _template("tmpl_b")]
        with patch("aion.routers.kairos.load_templates", return_value=templates):
            resp = client.get("/v1/kairos/templates")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["templates"]) == 2

    def test_empty_templates(self, client):
        with patch("aion.routers.kairos.load_templates", return_value=[]):
            resp = client.get("/v1/kairos/templates")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ── POST /v1/kairos/candidates/from-template ─────────────────────────────────


class TestCreateFromTemplate:
    def test_creates_candidate_returns_201(self, client):
        tmpl = _template("boleto_route")
        kairos = _mock_kairos()

        with patch("aion.routers.kairos.load_templates", return_value=[tmpl]), \
             patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                "/v1/kairos/candidates/from-template",
                json={"template_id": "boleto_route"},
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["template_id"] == "boleto_route"
        assert data["status"] == "draft"
        assert data["tenant_id"] == "tenant-1"
        kairos.store.save_candidate.assert_awaited_once()
        kairos.store.save_lifecycle_event.assert_awaited_once()

    def test_missing_tenant_returns_400(self, client):
        resp = client.post(
            "/v1/kairos/candidates/from-template",
            json={"template_id": "x"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_tenant"

    def test_missing_template_id_returns_400(self, client):
        resp = client.post(
            "/v1/kairos/candidates/from-template",
            json={},
            headers={"X-Aion-Tenant": "tenant-1"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_template_id"

    def test_unknown_template_returns_404(self, client):
        with patch("aion.routers.kairos.load_templates", return_value=[]):
            resp = client.post(
                "/v1/kairos/candidates/from-template",
                json={"template_id": "nonexistent"},
                headers={"X-Aion-Tenant": "tenant-1"},
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "template_not_found"

    def test_custom_title_overrides_template(self, client):
        tmpl = _template("tmpl_x")
        kairos = _mock_kairos()

        with patch("aion.routers.kairos.load_templates", return_value=[tmpl]), \
             patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                "/v1/kairos/candidates/from-template",
                json={"template_id": "tmpl_x", "title": "My Custom Title"},
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        assert resp.status_code == 201
        assert resp.json()["title"] == "My Custom Title"

    def test_kairos_disabled_returns_503(self, client):
        tmpl = _template("tmpl_y")
        with patch("aion.routers.kairos.load_templates", return_value=[tmpl]), \
             patch("aion.routers.kairos.get_kairos", side_effect=RuntimeError("KAIROS is disabled")):
            resp = client.post(
                "/v1/kairos/candidates/from-template",
                json={"template_id": "tmpl_y"},
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "kairos_unavailable"

    def test_candidate_save_fails_returns_500(self, client):
        tmpl = _template("tmpl_z")
        kairos = _mock_kairos()
        kairos.store.save_candidate = AsyncMock(side_effect=Exception("db error"))

        with patch("aion.routers.kairos.load_templates", return_value=[tmpl]), \
             patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                "/v1/kairos/candidates/from-template",
                json={"template_id": "tmpl_z"},
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        assert resp.status_code == 500

    def test_lifecycle_event_save_failure_still_returns_201(self, client):
        """Lifecycle event save is non-critical — candidate creation must succeed."""
        tmpl = _template("tmpl_ok")
        kairos = _mock_kairos()
        kairos.store.save_lifecycle_event = AsyncMock(side_effect=Exception("event save failed"))

        with patch("aion.routers.kairos.load_templates", return_value=[tmpl]), \
             patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                "/v1/kairos/candidates/from-template",
                json={"template_id": "tmpl_ok"},
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        assert resp.status_code == 201
        kairos.store.save_candidate.assert_awaited_once()


# ── GET /v1/kairos/candidates ─────────────────────────────────────────────────


class TestListCandidates:
    def test_lists_candidates_for_tenant(self, client):
        c1 = _candidate()
        c2 = _candidate(status=PolicyCandidateStatus.SHADOW_RUNNING)
        kairos = _mock_kairos(candidates=[c1, c2])

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.get(
                "/v1/kairos/candidates",
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_missing_tenant_returns_400(self, client):
        resp = client.get("/v1/kairos/candidates")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_tenant"

    def test_passes_status_filter(self, client):
        kairos = _mock_kairos(candidates=[])

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            client.get(
                "/v1/kairos/candidates?status=shadow_running",
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        call_kwargs = kairos.store.list_candidates.call_args
        assert "shadow_running" in str(call_kwargs)

    def test_passes_type_filter(self, client):
        kairos = _mock_kairos(candidates=[])

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            client.get(
                "/v1/kairos/candidates?type=guardrail",
                headers={"X-Aion-Tenant": "tenant-1"},
            )

        call_kwargs = kairos.store.list_candidates.call_args
        assert "guardrail" in str(call_kwargs)

    def test_kairos_disabled_returns_503(self, client):
        with patch("aion.routers.kairos.get_kairos", side_effect=RuntimeError("disabled")):
            resp = client.get(
                "/v1/kairos/candidates",
                headers={"X-Aion-Tenant": "tenant-1"},
            )
        assert resp.status_code == 503


# ── GET /v1/kairos/candidates/{id} ────────────────────────────────────────────


class TestGetCandidate:
    def test_returns_candidate_with_events(self, client):
        c = _candidate()
        event = _event(c.id)
        kairos = _mock_kairos(candidate=c, events=[event])

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.get(
                f"/v1/kairos/candidates/{c.id}",
                headers={"X-Aion-Tenant": "tenant-test"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["candidate"]["id"] == c.id
        assert len(data["lifecycle_events"]) == 1
        assert data["shadow_run"] is None

    def test_returns_shadow_run_when_present(self, client):
        c = _candidate(status=PolicyCandidateStatus.SHADOW_RUNNING)
        run = _shadow_run(c.id)
        c = c.model_copy(update={"shadow_run_id": run.id})
        kairos = _mock_kairos(candidate=c, shadow_run=run, events=[])

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.get(
                f"/v1/kairos/candidates/{c.id}",
                headers={"X-Aion-Tenant": "tenant-test"},
            )

        assert resp.status_code == 200
        assert resp.json()["shadow_run"] is not None
        assert resp.json()["shadow_run"]["id"] == run.id

    def test_not_found_returns_404(self, client):
        kairos = _mock_kairos(candidate=None)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.get(
                "/v1/kairos/candidates/nonexistent",
                headers={"X-Aion-Tenant": "tenant-test"},
            )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"

    def test_tenant_mismatch_returns_404(self, client):
        """Candidate from another tenant must appear as not found (defense-in-depth)."""
        c = _candidate(tenant_id="other-tenant")
        kairos = _mock_kairos(candidate=c)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.get(
                f"/v1/kairos/candidates/{c.id}",
                headers={"X-Aion-Tenant": "requesting-tenant"},
            )

        assert resp.status_code == 404

    def test_missing_tenant_returns_400(self, client):
        resp = client.get("/v1/kairos/candidates/some-id")
        assert resp.status_code == 400


# ── POST /v1/kairos/candidates/{id}/shadow ────────────────────────────────────


class TestStartShadow:
    def test_starts_shadow_run(self, client):
        c = _candidate(status=PolicyCandidateStatus.READY_FOR_SHADOW)
        run = _shadow_run(c.id)
        c_updated = c.model_copy(update={
            "status": PolicyCandidateStatus.SHADOW_RUNNING,
            "shadow_run_id": run.id,
        })
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.start_shadow = AsyncMock(return_value=(c_updated, run))

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/shadow",
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "op-1"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["candidate"]["status"] == "shadow_running"
        assert data["shadow_run"]["id"] == run.id

    def test_actor_id_is_optional(self, client):
        """X-Aion-Actor-Id is not required for shadow start."""
        c = _candidate(status=PolicyCandidateStatus.READY_FOR_SHADOW)
        run = _shadow_run(c.id)
        c_updated = c.model_copy(update={"status": PolicyCandidateStatus.SHADOW_RUNNING})
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.start_shadow = AsyncMock(return_value=(c_updated, run))

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/shadow",
                headers={"X-Aion-Tenant": "tenant-test"},
                # No X-Aion-Actor-Id
            )

        assert resp.status_code == 200

    def test_invalid_transition_returns_409(self, client):
        c = _candidate(status=PolicyCandidateStatus.DRAFT)
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.start_shadow = AsyncMock(side_effect=ValueError("not allowed"))

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/shadow",
                headers={"X-Aion-Tenant": "tenant-test"},
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "invalid_transition"

    def test_candidate_not_found_returns_404(self, client):
        kairos = _mock_kairos(candidate=None)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                "/v1/kairos/candidates/missing/shadow",
                headers={"X-Aion-Tenant": "tenant-test"},
            )

        assert resp.status_code == 404

    def test_tenant_mismatch_returns_404(self, client):
        c = _candidate(tenant_id="other-tenant")
        kairos = _mock_kairos(candidate=c)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/shadow",
                headers={"X-Aion-Tenant": "requesting-tenant"},
            )

        assert resp.status_code == 404

    def test_missing_tenant_returns_400(self, client):
        resp = client.post("/v1/kairos/candidates/some-id/shadow")
        assert resp.status_code == 400


# ── POST /v1/kairos/candidates/{id}/approve ──────────────────────────────────


class TestApprove:
    def test_approves_candidate(self, client):
        c = _candidate(status=PolicyCandidateStatus.SHADOW_COMPLETED)
        c_approved = c.model_copy(update={
            "status": PolicyCandidateStatus.APPROVED_PRODUCTION,
            "approved_by": "admin-1",
        })
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.approve = AsyncMock(return_value=c_approved)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/approve",
                json={"reason": "meets all criteria"},
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "approved_production"
        kairos.lifecycle_manager.approve.assert_awaited_once()

    def test_approve_with_empty_body_still_works(self, client):
        """Body is optional for approve — empty body must not break the endpoint."""
        c = _candidate(status=PolicyCandidateStatus.SHADOW_COMPLETED)
        c_approved = c.model_copy(update={"status": PolicyCandidateStatus.APPROVED_PRODUCTION})
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.approve = AsyncMock(return_value=c_approved)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/approve",
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
                # No body at all
            )

        assert resp.status_code == 200

    def test_missing_actor_returns_400(self, client):
        resp = client.post(
            "/v1/kairos/candidates/some-id/approve",
            json={"reason": "ok"},
            headers={"X-Aion-Tenant": "tenant-test"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_actor"

    def test_missing_tenant_returns_400(self, client):
        resp = client.post(
            "/v1/kairos/candidates/some-id/approve",
            headers={"X-Aion-Actor-Id": "admin-1"},
        )
        assert resp.status_code == 400

    def test_invalid_transition_returns_409(self, client):
        c = _candidate(status=PolicyCandidateStatus.DRAFT)
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.approve = AsyncMock(side_effect=ValueError("not allowed"))

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/approve",
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 409

    def test_candidate_not_found_returns_404(self, client):
        kairos = _mock_kairos(candidate=None)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                "/v1/kairos/candidates/missing/approve",
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 404

    def test_tenant_mismatch_returns_404(self, client):
        c = _candidate(tenant_id="other-tenant")
        kairos = _mock_kairos(candidate=c)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/approve",
                headers={"X-Aion-Tenant": "requesting-tenant", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 404

    def test_kairos_disabled_returns_503(self, client):
        with patch("aion.routers.kairos.get_kairos", side_effect=RuntimeError("disabled")):
            resp = client.post(
                "/v1/kairos/candidates/some-id/approve",
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )
        assert resp.status_code == 503


# ── POST /v1/kairos/candidates/{id}/reject ────────────────────────────────────


class TestReject:
    def test_rejects_candidate(self, client):
        c = _candidate(status=PolicyCandidateStatus.SHADOW_COMPLETED)
        c_rejected = c.model_copy(update={
            "status": PolicyCandidateStatus.REJECTED,
            "rejection_reason": "too many false positives",
        })
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.reject = AsyncMock(return_value=c_rejected)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/reject",
                json={"reason": "too many false positives"},
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        kairos.lifecycle_manager.reject.assert_awaited_once()

    def test_missing_reason_returns_400(self, client):
        resp = client.post(
            "/v1/kairos/candidates/some-id/reject",
            json={},
            headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_reason"

    def test_missing_actor_returns_400(self, client):
        resp = client.post(
            "/v1/kairos/candidates/some-id/reject",
            json={"reason": "bad policy"},
            headers={"X-Aion-Tenant": "tenant-test"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "missing_actor"

    def test_missing_tenant_returns_400(self, client):
        resp = client.post(
            "/v1/kairos/candidates/some-id/reject",
            json={"reason": "bad policy"},
            headers={"X-Aion-Actor-Id": "admin-1"},
        )
        assert resp.status_code == 400

    def test_invalid_transition_returns_409(self, client):
        c = _candidate(status=PolicyCandidateStatus.DRAFT)
        kairos = _mock_kairos(candidate=c)
        kairos.lifecycle_manager.reject = AsyncMock(side_effect=ValueError("not allowed"))

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/reject",
                json={"reason": "test"},
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 409

    def test_candidate_not_found_returns_404(self, client):
        kairos = _mock_kairos(candidate=None)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                "/v1/kairos/candidates/missing/reject",
                json={"reason": "test"},
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 404

    def test_tenant_mismatch_returns_404(self, client):
        c = _candidate(tenant_id="other-tenant")
        kairos = _mock_kairos(candidate=c)

        with patch("aion.routers.kairos.get_kairos", return_value=kairos):
            resp = client.post(
                f"/v1/kairos/candidates/{c.id}/reject",
                json={"reason": "test"},
                headers={"X-Aion-Tenant": "requesting-tenant", "X-Aion-Actor-Id": "admin-1"},
            )

        assert resp.status_code == 404

    def test_kairos_disabled_returns_503(self, client):
        with patch("aion.routers.kairos.get_kairos", side_effect=RuntimeError("disabled")):
            resp = client.post(
                "/v1/kairos/candidates/some-id/reject",
                json={"reason": "test"},
                headers={"X-Aion-Tenant": "tenant-test", "X-Aion-Actor-Id": "admin-1"},
            )
        assert resp.status_code == 503
