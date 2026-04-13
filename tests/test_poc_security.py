"""Tests for POC enterprise security features.

Covers: CORS, security headers, chat auth, tenant enforcement,
per-tenant rate limits, readiness probe, data retention TTL.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def _reset_singletons():
    """Reset config singletons so env overrides take effect."""
    import aion.config as cfg
    old = cfg._settings
    cfg._settings = None
    yield
    cfg._settings = old


# ── Security Headers ──

def test_security_headers_present():
    """All security headers are set on responses."""
    # Import fresh to pick up middleware
    from aion.main import app
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"


# ── Readiness Probe ──

def test_readiness_endpoint_exists():
    from aion.main import app
    client = TestClient(app)
    resp = client.get("/ready")
    # After startup, pipeline should be ready
    assert resp.status_code in (200, 503)
    assert "ready" in resp.json()


def test_health_includes_ready_field():
    from aion.main import app
    client = TestClient(app)
    resp = client.get("/health")
    data = resp.json()
    assert "ready" in data


# ── Tenant enforcement ──

def test_require_tenant_rejects_missing_header(_reset_singletons):
    """When require_tenant=true, requests without X-Aion-Tenant get 400."""
    with patch.dict(os.environ, {"AION_REQUIRE_TENANT": "true"}):
        import aion.config as cfg
        cfg._settings = None

        from aion.main import app
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            # No X-Aion-Tenant header
        )
        assert resp.status_code == 400
        assert "tenant_required" in resp.json()["error"]["code"]


def test_require_tenant_accepts_with_header(_reset_singletons):
    """When require_tenant=true, requests with header pass tenant validation."""
    with patch.dict(os.environ, {"AION_REQUIRE_TENANT": "true"}):
        import aion.config as cfg
        cfg._settings = None

        from aion.main import app
        client = TestClient(app)

        # This should pass tenant validation (may fail later on LLM forward, that's ok)
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Aion-Tenant": "test-corp"},
        )
        # Should NOT be 400 with tenant_required
        if resp.status_code == 400:
            assert resp.json()["error"]["code"] != "tenant_required"


# ── Chat auth ──

def test_require_chat_auth_rejects_without_key(_reset_singletons):
    """When require_chat_auth=true, chat endpoint requires API key."""
    with patch.dict(os.environ, {
        "AION_REQUIRE_CHAT_AUTH": "true",
        "AION_ADMIN_KEY": "test-key-123:admin",
    }):
        import aion.config as cfg
        cfg._settings = None

        from aion.main import app
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401


def test_require_chat_auth_accepts_with_key(_reset_singletons):
    """When require_chat_auth=true, valid key is accepted."""
    with patch.dict(os.environ, {
        "AION_REQUIRE_CHAT_AUTH": "true",
        "AION_ADMIN_KEY": "test-key-123:admin",
    }):
        import aion.config as cfg
        cfg._settings = None

        from aion.main import app
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test-key-123"},
        )
        # Should pass auth (may fail on LLM forward)
        assert resp.status_code != 401


# ── Configurable rate limits ──

def test_chat_rate_limit_is_configurable(_reset_singletons):
    """chat_rate_limit setting controls the limit."""
    with patch.dict(os.environ, {"AION_CHAT_RATE_LIMIT": "200"}):
        import aion.config as cfg
        cfg._settings = None
        settings = cfg.get_settings()
        assert settings.chat_rate_limit == 200


def test_admin_rate_limit_is_configurable(_reset_singletons):
    with patch.dict(os.environ, {"AION_ADMIN_RATE_LIMIT": "50"}):
        import aion.config as cfg
        cfg._settings = None
        settings = cfg.get_settings()
        assert settings.admin_rate_limit == 50


# ── CORS origins configurable ──

def test_cors_origins_configurable(_reset_singletons):
    with patch.dict(os.environ, {"AION_CORS_ORIGINS": "http://localhost:3000,https://console.acme.io"}):
        import aion.config as cfg
        cfg._settings = None
        settings = cfg.get_settings()
        origins = [o.strip() for o in settings.cors_origins.split(",")]
        assert "http://localhost:3000" in origins
        assert "https://console.acme.io" in origins


# ── Data retention ──

def test_telemetry_retention_configurable(_reset_singletons):
    with patch.dict(os.environ, {"AION_TELEMETRY_RETENTION_HOURS": "24"}):
        import aion.config as cfg
        cfg._settings = None
        settings = cfg.get_settings()
        assert settings.telemetry_retention_hours == 24


# ── OpenAPI schema ──

def test_openapi_has_tags():
    """OpenAPI schema includes our custom tags."""
    from aion.main import app
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    tag_names = [t["name"] for t in schema.get("tags", [])]
    assert "LLM Proxy" in tag_names
    assert "Control Plane" in tag_names
    assert "Observability" in tag_names
    assert "Data Management" in tag_names
