"""Unit tests for aion/kairos/telemetry.py — Fase 5: Sanitized Telemetry.

Tests cover:
- _hash(): one-way SHA-256
- _bucket_timestamp(): rounds to nearest hour, handles naive datetimes
- _bucket_observations(): correct range strings at all boundaries
- _safe_rate(): division and edge cases
- _sanitize_template_id(): allowlist enforcement
- _sanitize_policy_type(): allowlist enforcement
- _build_payload(): no raw identifiers, no PII, shadow fields conditional
- KairosTelemetryExporter.active: enabled only when all three settings present
- emit_lifecycle_transition(): no-op when inactive, sends when active, swallows errors
- api_key validation: rejects control chars
- Lifecycle integration: approve/reject emit via fire-and-forget (asyncio.create_task)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aion.kairos.telemetry import (
    KairosTelemetryExporter,
    _bucket_observations,
    _bucket_timestamp,
    _build_payload,
    _hash,
    _safe_rate,
    _sanitize_actor_type,
    _sanitize_status,
    _sanitize_template_id,
    _sanitize_policy_type,
    get_telemetry_exporter,
    reset_telemetry_exporter,
)
from aion.kairos.models import PolicyCandidate, PolicyCandidateStatus, ShadowRun, ShadowRunStatus
from aion.kairos.settings import KairosSettings


# ── Helpers ───────────────────────────────────────────────────────────────────


def _candidate(**kwargs) -> PolicyCandidate:
    now = datetime.now(timezone.utc).isoformat()
    defaults = {
        "id": str(uuid.uuid4()),
        "tenant_id": "tenant-abc",
        "type": "bypass",
        "status": PolicyCandidateStatus.SHADOW_COMPLETED,
        "title": "Test",
        "business_summary": "Some customer business reason",
        "technical_summary": "Technical details go here",
        "template_id": "greeting_bypass",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    return PolicyCandidate(**defaults)


def _run(candidate_id: str, obs: int = 1000, matched: int = 740, fallback: int = 80) -> ShadowRun:
    return ShadowRun(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        tenant_id="tenant-abc",
        status=ShadowRunStatus.COMPLETED,
        observations_count=obs,
        matched_count=matched,
        fallback_count=fallback,
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def _settings(**kwargs) -> KairosSettings:
    defaults = {"storage_mode": "sqlite"}
    defaults.update(kwargs)
    return KairosSettings(**defaults)


def _active_settings() -> KairosSettings:
    return _settings(
        telemetry_enabled=True,
        telemetry_endpoint="https://telemetry.example.com/v1/ingest",
        telemetry_api_key="test-key",
    )


# ── Helper functions ──────────────────────────────────────────────────────────


class TestHash:
    def test_returns_sha256_hex(self):
        result = _hash("some-id")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_deterministic(self):
        assert _hash("abc") == _hash("abc")

    def test_different_inputs_differ(self):
        assert _hash("tenant-a") != _hash("tenant-b")

    def test_raw_value_not_in_result(self):
        value = "raw-tenant-id-12345"
        assert value not in _hash(value)


class TestBucketTimestamp:
    def test_rounds_to_hour(self):
        dt = datetime(2026, 5, 6, 14, 37, 22, tzinfo=timezone.utc)
        result = _bucket_timestamp(dt)
        assert "14:00:00" in result
        assert "37" not in result

    def test_on_hour_boundary_unchanged(self):
        dt = datetime(2026, 5, 1, 3, 0, 0, tzinfo=timezone.utc)
        assert "03:00:00" in _bucket_timestamp(dt)

    def test_naive_datetime_treated_as_utc(self):
        naive = datetime(2026, 5, 6, 10, 30, 0)  # no tzinfo
        result = _bucket_timestamp(naive)
        assert "10:00:00" in result  # treated as UTC, rounded

    def test_aware_non_utc_converted(self):
        from datetime import timedelta
        brt = timezone(timedelta(hours=-3))
        dt_brt = datetime(2026, 5, 6, 14, 37, 0, tzinfo=brt)  # 14:37 BRT = 17:37 UTC
        result = _bucket_timestamp(dt_brt)
        assert "17:00:00" in result  # correctly converted to UTC hour

    def test_output_parseable(self):
        dt = datetime(2026, 5, 6, 10, 0, 0, tzinfo=timezone.utc)
        result = _bucket_timestamp(dt)
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed.minute == 0
        assert parsed.second == 0


class TestBucketObservations:
    def test_under_100(self):
        assert _bucket_observations(50) == "0-100"

    def test_exactly_100(self):
        assert _bucket_observations(100) == "100-250"

    def test_exactly_500(self):
        assert _bucket_observations(500) == "500-1000"

    def test_in_1000_to_2500(self):
        assert _bucket_observations(1500) == "1000-2500"

    def test_above_10000(self):
        assert _bucket_observations(50000) == "10000+"

    def test_zero(self):
        assert _bucket_observations(0) == "0-100"


class TestSafeRate:
    def test_normal_division(self):
        assert _safe_rate(740, 1000) == 0.74

    def test_zero_denominator_returns_none(self):
        assert _safe_rate(0, 0) is None

    def test_full_match(self):
        assert _safe_rate(100, 100) == 1.0

    def test_no_match(self):
        assert _safe_rate(0, 500) == 0.0

    def test_rounded_to_4_decimals(self):
        assert _safe_rate(1, 3) == round(1 / 3, 4)


class TestSanitizeTemplateId:
    def test_valid_public_id(self):
        assert _sanitize_template_id("greeting_bypass") == "greeting_bypass"

    def test_valid_with_hyphens(self):
        assert _sanitize_template_id("boleto-second-copy") == "boleto-second-copy"

    def test_none_returns_none(self):
        assert _sanitize_template_id(None) is None

    def test_too_long_returns_none(self):
        assert _sanitize_template_id("a" * 65) is None

    def test_customer_domain_name_with_uppercase_filtered(self):
        # Regex requires lowercase — mixed-case names are rejected
        assert _sanitize_template_id("AcmeCorp_Policy") is None

    def test_uppercase_filtered(self):
        assert _sanitize_template_id("MyTemplate") is None

    def test_spaces_filtered(self):
        assert _sanitize_template_id("my template") is None


class TestSanitizePolicyType:
    def test_known_types_pass(self):
        for t in ("bypass", "guardrail", "route_to_api", "handoff"):
            assert _sanitize_policy_type(t) == t

    def test_unknown_type_filtered(self):
        assert _sanitize_policy_type("customer_custom_type") is None
        assert _sanitize_policy_type("ByPass") is None  # case-sensitive


class TestSanitizeActorType:
    def test_known_types_pass(self):
        for t in ("operator", "sweep", "system"):
            assert _sanitize_actor_type(t) == t

    def test_unknown_actor_type_filtered(self):
        assert _sanitize_actor_type("alice@bigbank.com") is None
        assert _sanitize_actor_type("admin") is None
        assert _sanitize_actor_type("Operator") is None  # case-sensitive

    def test_empty_string_filtered(self):
        assert _sanitize_actor_type("") is None


class TestSanitizeStatus:
    def test_known_statuses_pass(self):
        known = [
            "draft", "ready_for_shadow", "shadow_running", "shadow_completed",
            "approved_production", "under_review", "rejected", "deprecated", "archived",
        ]
        for s in known:
            assert _sanitize_status(s) == s

    def test_none_returns_none(self):
        assert _sanitize_status(None) is None

    def test_unknown_status_filtered(self):
        assert _sanitize_status("active") is None
        assert _sanitize_status("Shadow_Running") is None  # case-sensitive
        assert _sanitize_status("unknown_state") is None


class TestBuildPayload:
    def test_no_raw_tenant_id(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        # tenant_id must not appear anywhere in serialized payload
        assert c.tenant_id not in str(payload)

    def test_no_raw_candidate_id(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert c.id not in str(payload)

    def test_no_business_summary(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert "business_summary" not in payload
        assert c.business_summary not in str(payload)

    def test_no_technical_summary(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert "technical_summary" not in payload
        assert c.technical_summary not in str(payload)

    def test_no_rejection_reason(self):
        c = _candidate(rejection_reason="customer not satisfied")
        payload = _build_payload(c, "shadow_completed", "rejected", "operator")
        assert "rejection_reason" not in payload
        assert "customer not satisfied" not in str(payload)

    def test_install_hash_is_hash_of_tenant_id(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["install_hash"] == _hash(c.tenant_id)

    def test_candidate_id_hash_is_hash_of_id(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["candidate_id_hash"] == _hash(c.id)

    def test_template_id_allowed_public_id(self):
        c = _candidate(template_id="greeting_bypass")
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["template_id"] == "greeting_bypass"

    def test_template_id_customer_name_filtered(self):
        c = _candidate(template_id="AcmeCorp_Special_Policy")  # uppercase → filtered
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["template_id"] is None

    def test_policy_type_unknown_filtered(self):
        c = _candidate(type="custom_type")
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["policy_type"] is None

    def test_shadow_fields_included_when_run_provided(self):
        c = _candidate()
        run = _run(c.id, obs=1000, matched=740, fallback=80)
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep", shadow_run=run)
        assert "shadow_match_rate" in payload
        assert "shadow_fallback_rate" in payload
        assert "shadow_observations_bucket" in payload
        assert payload["shadow_match_rate"] == 0.74
        assert payload["shadow_observations_bucket"] == "1000-2500"

    def test_shadow_fields_absent_when_no_run(self):
        c = _candidate()
        payload = _build_payload(c, "draft", "ready_for_shadow", "operator")
        assert "shadow_match_rate" not in payload
        assert "shadow_fallback_rate" not in payload

    def test_event_field_is_lifecycle_transition(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["event"] == "lifecycle_transition"

    def test_timestamp_bucket_is_on_hour(self):
        c = _candidate()
        payload = _build_payload(c, "draft", "ready_for_shadow", "operator")
        ts = payload["timestamp_bucket"]
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.minute == 0
        assert parsed.second == 0

    def test_actor_type_unknown_filtered(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "alice@bigbank.com")
        assert payload["actor_type"] is None

    def test_actor_type_known_passes(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["actor_type"] == "sweep"

    def test_from_status_unknown_filtered(self):
        c = _candidate()
        payload = _build_payload(c, "unknown_state", "shadow_completed", "sweep")
        assert payload["from_status"] is None

    def test_from_status_none_stays_none(self):
        c = _candidate()
        payload = _build_payload(c, None, "draft", "system")
        assert payload["from_status"] is None

    def test_to_status_unknown_filtered(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "hacked_state", "sweep")
        assert payload["to_status"] is None

    def test_known_statuses_pass_through(self):
        c = _candidate()
        payload = _build_payload(c, "shadow_running", "shadow_completed", "sweep")
        assert payload["from_status"] == "shadow_running"
        assert payload["to_status"] == "shadow_completed"


# ── KairosTelemetryExporter ───────────────────────────────────────────────────


class TestApiKeyValidation:
    def test_valid_key_accepted(self):
        exp = KairosTelemetryExporter(_active_settings())
        assert exp._api_key == "test-key"
        assert exp.active is True

    def test_key_with_newline_disables_exporter(self):
        settings = _settings(
            telemetry_enabled=True,
            telemetry_endpoint="https://telemetry.example.com",
            telemetry_api_key="key\ninjected-header",
        )
        exp = KairosTelemetryExporter(settings)
        assert exp.active is False  # invalid key → _api_key = "" → not active

    def test_key_with_carriage_return_disables_exporter(self):
        settings = _settings(
            telemetry_enabled=True,
            telemetry_endpoint="https://telemetry.example.com",
            telemetry_api_key="key\r",
        )
        exp = KairosTelemetryExporter(settings)
        assert exp.active is False

    def test_key_with_null_byte_disables_exporter(self):
        settings = _settings(
            telemetry_enabled=True,
            telemetry_endpoint="https://telemetry.example.com",
            telemetry_api_key="key\x00injected",
        )
        exp = KairosTelemetryExporter(settings)
        assert exp.active is False


class TestTelemetryExporterActive:
    def test_active_when_all_set(self):
        exp = KairosTelemetryExporter(_active_settings())
        assert exp.active is True

    def test_inactive_when_disabled(self):
        settings = _settings(
            telemetry_enabled=False,
            telemetry_endpoint="https://telemetry.example.com/v1/ingest",
            telemetry_api_key="secret-key",
        )
        exp = KairosTelemetryExporter(settings)
        assert exp.active is False

    def test_inactive_when_no_endpoint(self):
        settings = _settings(
            telemetry_enabled=True,
            telemetry_endpoint=None,
            telemetry_api_key="secret-key",
        )
        exp = KairosTelemetryExporter(settings)
        assert exp.active is False

    def test_inactive_when_no_api_key(self):
        settings = _settings(
            telemetry_enabled=True,
            telemetry_endpoint="https://telemetry.example.com/v1/ingest",
            telemetry_api_key=None,
        )
        exp = KairosTelemetryExporter(settings)
        assert exp.active is False

    def test_inactive_by_default(self):
        exp = KairosTelemetryExporter(_settings())
        assert exp.active is False


class TestTelemetryExporterEmit:
    async def test_inactive_exporter_does_not_call_send(self):
        exp = KairosTelemetryExporter(_settings())
        c = _candidate()
        with patch.object(exp, "_send", new=AsyncMock()) as mock_send:
            await exp.emit_lifecycle_transition(c, "draft", "ready_for_shadow", "operator")
        mock_send.assert_not_called()

    async def test_active_exporter_calls_send(self):
        exp = KairosTelemetryExporter(_active_settings())
        c = _candidate()
        with patch.object(exp, "_send", new=AsyncMock()) as mock_send:
            await exp.emit_lifecycle_transition(c, "shadow_running", "shadow_completed", "sweep")
        mock_send.assert_called_once()

    async def test_send_receives_sanitized_payload(self):
        exp = KairosTelemetryExporter(_active_settings())
        c = _candidate()
        captured = {}

        async def capture(payload):
            captured.update(payload)

        with patch.object(exp, "_send", side_effect=capture):
            await exp.emit_lifecycle_transition(c, "shadow_running", "shadow_completed", "sweep")

        assert c.tenant_id not in str(captured)
        assert c.id not in str(captured)
        assert c.business_summary not in str(captured)
        assert captured["event"] == "lifecycle_transition"

    async def test_send_error_is_swallowed(self):
        exp = KairosTelemetryExporter(_active_settings())
        c = _candidate()
        with patch.object(exp, "_send", side_effect=Exception("network error")):
            await exp.emit_lifecycle_transition(c, "draft", "ready_for_shadow", "operator")
        # Must not raise

    async def test_inactive_means_no_http_activity(self):
        """When telemetry is disabled, absolutely no network activity should occur."""
        exp = KairosTelemetryExporter(_settings())  # telemetry_enabled=False
        c = _candidate()
        with patch("httpx.AsyncClient") as mock_client:
            await exp.emit_lifecycle_transition(c, "draft", "ready_for_shadow", "operator")
        mock_client.assert_not_called()

    async def test_send_includes_shadow_run_metrics(self):
        exp = KairosTelemetryExporter(_active_settings())
        c = _candidate()
        run = _run(c.id, obs=800, matched=600, fallback=50)
        captured = {}

        async def capture(payload):
            captured.update(payload)

        with patch.object(exp, "_send", side_effect=capture):
            await exp.emit_lifecycle_transition(
                c, "shadow_running", "shadow_completed", "sweep", shadow_run=run
            )

        assert "shadow_match_rate" in captured
        assert captured["shadow_match_rate"] == round(600 / 800, 4)
        assert captured["shadow_observations_bucket"] == "500-1000"


# ── Singleton ──────────────────────────────────────────────────────────────────


class TestGetTelemetryExporter:
    def setup_method(self):
        reset_telemetry_exporter()

    def teardown_method(self):
        reset_telemetry_exporter()

    def test_returns_exporter(self):
        with patch("aion.kairos.settings.get_kairos_settings", return_value=_settings()):
            exp = get_telemetry_exporter()
        assert isinstance(exp, KairosTelemetryExporter)

    def test_same_instance_returned(self):
        with patch("aion.kairos.settings.get_kairos_settings", return_value=_settings()):
            exp1 = get_telemetry_exporter()
            exp2 = get_telemetry_exporter()
        assert exp1 is exp2

    def test_reset_forces_new_instance(self):
        with patch("aion.kairos.settings.get_kairos_settings", return_value=_settings()):
            exp1 = get_telemetry_exporter()
        reset_telemetry_exporter()
        with patch("aion.kairos.settings.get_kairos_settings", return_value=_settings()):
            exp2 = get_telemetry_exporter()
        assert exp1 is not exp2


# ── Lifecycle integration ──────────────────────────────────────────────────────


class TestLifecycleTelemetryIntegration:
    """Verify that approve/reject/sweep emit telemetry fire-and-forget."""

    def setup_method(self):
        reset_telemetry_exporter()

    def teardown_method(self):
        reset_telemetry_exporter()

    def _make_lifecycle_manager(self):
        from aion.kairos.lifecycle import KairosLifecycleManager
        settings = _settings()
        store = MagicMock()
        store.save_candidate = AsyncMock()
        store.save_lifecycle_event = AsyncMock()
        store.save_shadow_run = AsyncMock()
        return KairosLifecycleManager(store, settings)

    async def test_approve_fires_telemetry_task(self):
        mgr = self._make_lifecycle_manager()
        c = _candidate(status=PolicyCandidateStatus.SHADOW_COMPLETED)

        emitted = []

        async def fake_emit(candidate, from_status, to_status, actor_type, shadow_run=None):
            emitted.append(to_status)

        with patch("aion.kairos.telemetry.get_telemetry_exporter") as mock_getter:
            mock_exp = MagicMock()
            mock_exp.active = True
            mock_exp.emit_lifecycle_transition = AsyncMock(side_effect=fake_emit)
            mock_getter.return_value = mock_exp
            await mgr.approve(c, actor_id="operator-1")

            # Allow background tasks to run
            import asyncio
            await asyncio.sleep(0)

        assert "approved_production" in emitted

    async def test_reject_fires_telemetry_task(self):
        mgr = self._make_lifecycle_manager()
        c = _candidate(status=PolicyCandidateStatus.SHADOW_COMPLETED)

        emitted = []

        async def fake_emit(candidate, from_status, to_status, actor_type, shadow_run=None):
            emitted.append(to_status)

        with patch("aion.kairos.telemetry.get_telemetry_exporter") as mock_getter:
            mock_exp = MagicMock()
            mock_exp.active = True
            mock_exp.emit_lifecycle_transition = AsyncMock(side_effect=fake_emit)
            mock_getter.return_value = mock_exp
            await mgr.reject(c, actor_id="operator-1", reason="not effective")

            import asyncio
            await asyncio.sleep(0)

        assert "rejected" in emitted

    async def test_telemetry_disabled_default_no_http(self):
        """Default settings (telemetry_enabled=False) must make zero HTTP calls."""
        mgr = self._make_lifecycle_manager()
        c = _candidate(status=PolicyCandidateStatus.SHADOW_COMPLETED)

        with patch("aion.kairos.settings.get_kairos_settings", return_value=_settings()):
            with patch("httpx.AsyncClient") as mock_client:
                await mgr.approve(c, actor_id="operator-1")
                import asyncio
                await asyncio.sleep(0)

        mock_client.assert_not_called()
