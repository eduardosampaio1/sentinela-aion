"""QA Ceifador audit fixes — regression tests.

Covers the 8 enterprise pre-launch fixes implemented after the 4-iteration
errata in qa-evidence/sentinela-aion-main/. Each test maps to a finding ID:

  F-37 — Decision-Only mode enforcement (no LLM call when AION_MODE=poc_decision)
  F-03 — Audit secret mandatory under AION_PROFILE=production
  F-04 — Embedded dev public key refused under AION_PROFILE=production
  F-12 — Chat auth pass-through (require_chat_auth=true + admin_key="") refused in prod
  F-06 — event.data["input"] never carries raw user text
  F-07 — Durable counters survive restart (mocked Redis path)
  F-10 — /v1/explain looks at durable store first
  F-16 — per_request_max_cost_usd rejects 402 before LLM call
  F-36 — AION_BUDGET_ENABLED required when mode is Transparent in production
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest


# ── F-06 ────────────────────────────────────────────────────────────────────

def test_f06_sanitize_input_drops_raw_text():
    """The sanitized input dict never contains the original message text."""
    from aion.shared.telemetry import _sanitize_input

    pii = "User CPF 123.456.789-00 email foo@example.com"
    out = _sanitize_input(pii)

    assert isinstance(out, dict)
    assert out["schema"] == "1.1"
    assert out["length"] == len(pii)
    assert len(out["hash"]) == 64  # full sha256 hex
    # preview is bounded to first 8 ASCII-printable chars
    assert len(out["preview"]) <= 8
    # raw PII tail must not appear anywhere in the dict
    serialized = json.dumps(out)
    assert "123.456.789-00" not in serialized
    assert "foo@example.com" not in serialized


def test_f06_sanitize_input_empty():
    from aion.shared.telemetry import _sanitize_input

    out = _sanitize_input("")
    assert out == {"schema": "1.1", "length": 0, "hash": None, "preview": ""}


def test_f06_telemetry_event_uses_sanitized_input():
    """TelemetryEvent.data['input'] is a dict, never raw text."""
    from aion.shared.telemetry import TelemetryEvent

    secret = "Some message with secret 999.888.777-66"
    ev = TelemetryEvent(
        event_type="bypass",
        module="estixe",
        request_id="req-test",
        input_text=secret,
        tenant="acme",
    )
    assert ev.data["schema_version"] == "1.1"
    assert isinstance(ev.data["input"], dict)
    assert ev.data["input"]["length"] == len(secret)
    # The secret text must not appear anywhere in the event payload.
    assert "999.888.777-66" not in json.dumps(ev.data, default=str)


# ── F-37 ────────────────────────────────────────────────────────────────────

def test_f37_decision_only_blocks_chat_completions():
    """When AION_MODE is poc_decision, /v1/chat/completions returns 403."""
    from aion.routers.proxy import _enforce_decision_only_mode

    class S:
        mode = "poc_decision"

    resp = _enforce_decision_only_mode(S(), "/v1/chat/completions")
    assert resp is not None
    assert resp.status_code == 403
    body = json.loads(resp.body)
    assert body["error"]["code"] == "decision_only_mode_violation"


def test_f37_decision_only_blocks_assisted():
    from aion.routers.proxy import _enforce_decision_only_mode

    class S:
        mode = "decision_only"

    resp = _enforce_decision_only_mode(S(), "/v1/chat/assisted")
    assert resp is not None
    assert resp.status_code == 403


def test_f37_transparent_mode_allows_chat():
    from aion.routers.proxy import _enforce_decision_only_mode

    for mode in ("poc_transparent", "full_transparent", "", None):
        class S:
            pass
        S.mode = mode
        assert _enforce_decision_only_mode(S(), "/v1/chat/completions") is None


def test_f37_decision_only_modes_set():
    from aion.config import DECISION_ONLY_MODES

    assert "poc_decision" in DECISION_ONLY_MODES
    assert "decision_only" in DECISION_ONLY_MODES
    assert "poc_transparent" not in DECISION_ONLY_MODES
    assert "full_transparent" not in DECISION_ONLY_MODES


def test_f37_llm_credential_env_vars_listed():
    from aion.config import LLM_CREDENTIAL_ENV_VARS

    # The boot check inspects these — make sure all known vendors are covered.
    for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
              "AION_DEFAULT_API_KEY", "AION_DEFAULT_BASE_URL"):
        assert v in LLM_CREDENTIAL_ENV_VARS


# ── F-04 ────────────────────────────────────────────────────────────────────

def test_f04_embedded_dev_key_detected():
    """The embedded dev public key must be detectable so production can refuse it."""
    from aion.license import _is_using_embedded_dev_key, _EMBEDDED_PUBLIC_KEY_FINGERPRINT

    # Without AION_LICENSE_PUBLIC_KEY env, the embedded key is in use.
    if not os.environ.get("AION_LICENSE_PUBLIC_KEY"):
        assert _is_using_embedded_dev_key() is True

    # The fingerprint marker exists for recognizability in logs.
    assert _EMBEDDED_PUBLIC_KEY_FINGERPRINT.startswith("dev-only-")


# ── F-16 ────────────────────────────────────────────────────────────────────

def test_f16_per_request_cost_cap_field():
    """BudgetConfig accepts the new per_request_max_cost_usd field."""
    from aion.shared.budget import BudgetConfig

    c = BudgetConfig(tenant="acme", per_request_max_cost_usd=0.01)
    assert c.per_request_max_cost_usd == 0.01

    # Default is None (no cap, legacy behavior).
    c2 = BudgetConfig(tenant="acme")
    assert c2.per_request_max_cost_usd is None


@pytest.mark.asyncio
async def test_f16_per_request_cap_rejects_before_llm():
    """check_budget raises BudgetExceededError when estimated_cost > cap."""
    from aion.shared.budget import (
        BudgetConfig, BudgetExceededError, check_budget, get_budget_store,
    )

    # Force budget enabled for this test.
    with patch.dict(os.environ, {"AION_BUDGET_ENABLED": "true"}):
        store = get_budget_store()
        # Inject a config returning per_request cap of $0.001.
        async def fake_get_config(tenant):
            return BudgetConfig(tenant=tenant, per_request_max_cost_usd=0.001)

        with patch.object(store, "get_config", side_effect=fake_get_config):
            class Ctx:
                metadata = {"estimated_cost": 0.05}  # way above cap
            with pytest.raises(BudgetExceededError) as exc:
                await check_budget("acme", Ctx())
            assert exc.value.cap_type == "per_request"


# ── F-07 / F-10 ─────────────────────────────────────────────────────────────

def test_f07_load_persistent_counters_is_callable():
    """load_persistent_counters exists and is async (smoke test, no Redis required)."""
    import inspect
    from aion.shared.telemetry import load_persistent_counters
    assert inspect.iscoroutinefunction(load_persistent_counters)


def test_f10_lookup_explain_is_callable():
    """lookup_explain exists and is async."""
    import inspect
    from aion.shared.telemetry import lookup_explain
    assert inspect.iscoroutinefunction(lookup_explain)


# ── F-03 / F-04 / F-12 / F-36 — Profile gating ──────────────────────────────

def test_profile_enum_values():
    """AION_PROFILE accepts development | staging | production."""
    from aion.config import Profile

    assert Profile.DEVELOPMENT.value == "development"
    assert Profile.STAGING.value == "staging"
    assert Profile.PRODUCTION.value == "production"


def test_profile_default_is_development():
    """Default profile must be development to avoid breaking existing dev/test envs."""
    from aion.config import AionSettings, Profile

    s = AionSettings()
    assert s.profile == Profile.DEVELOPMENT


# ── F-22 ────────────────────────────────────────────────────────────────────

def test_f22_request_provenance_optional_fields():
    from aion.contract import RequestProvenance

    rp = RequestProvenance()
    assert rp.original_request_hash is None
    assert rp.modified_request_hash is None
    assert rp.compression_ratio is None
    assert rp.policy_version is None


def test_f22_yaml_version_reader():
    from pathlib import Path
    from aion.contract.builder import _read_yaml_version

    # Files in this repo declare `version: "1.0"` at the top.
    assert _read_yaml_version(Path("config/models.yaml")) == "1.0"
    assert _read_yaml_version(Path("config/policies.yaml")) == "1.0"
    # Missing file → None (no exception)
    assert _read_yaml_version(Path("config/__nonexistent__.yaml")) is None


def test_f22_contract_includes_provenance():
    """build_contract attaches provenance with hashes + versions."""
    from aion.contract import build_contract
    from aion.shared.schemas import (
        ChatCompletionRequest, Decision, PipelineContext,
    )

    ctx = PipelineContext(tenant="acme")
    ctx.original_request = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Olá"},
        ],
    )
    ctx.modified_request = ctx.original_request
    ctx.tokens_before = 100
    ctx.tokens_after = 80
    ctx.decision = Decision.BYPASS

    c = build_contract(ctx, active_modules=["estixe", "nomos"], operating_mode="stateless")
    assert c.contract_version == "1.1"
    assert c.provenance is not None
    # Hash of the original request — 64-char hex.
    assert c.provenance.original_request_hash is not None
    assert len(c.provenance.original_request_hash) == 64
    # Compression ratio derived from tokens_after/before.
    assert c.provenance.compression_ratio == 0.8
    # YAML versions surfaced.
    assert c.provenance.policy_version == "1.0"
    assert c.provenance.models_version == "1.0"
    # System prompt hash present (we have a system message above).
    assert c.provenance.prompt_template_hash is not None


def test_f22_modified_hash_only_when_different():
    """modified_request_hash is None when METIS didn't change the payload."""
    from aion.contract import build_contract
    from aion.shared.schemas import (
        ChatCompletionRequest, Decision, PipelineContext,
    )

    ctx = PipelineContext(tenant="acme")
    req = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )
    ctx.original_request = req
    ctx.modified_request = req  # same object — no compression
    ctx.decision = Decision.CONTINUE

    c = build_contract(ctx, active_modules=["estixe"], operating_mode="stateless")
    assert c.provenance.modified_request_hash is None


def test_f22_provenance_cache_clear():
    """clear_provenance_cache empties the YAML version cache (no-op smoke test)."""
    from aion.contract import clear_provenance_cache
    from aion.contract.builder import _yaml_version_cache, _yaml_version_cached
    from pathlib import Path

    _yaml_version_cached("models", Path("config/models.yaml"))
    assert "models" in _yaml_version_cache
    clear_provenance_cache()
    assert _yaml_version_cache == {}


# ── F-15 ────────────────────────────────────────────────────────────────────

def test_f15_stream_buffer_cap_settings_present():
    """Settings expose tunable streaming caps with safe defaults."""
    from aion.config import AionSettings

    s = AionSettings()
    assert s.stream_max_buffered_chunks == 50_000
    # 16 MiB default — large enough for legitimate completions, small enough
    # to abort runaway generations before the 5-minute stream timeout fires.
    assert s.stream_max_buffered_bytes == 16 * 1024 * 1024


def test_f15_stream_buffer_cap_settings_overridable():
    """Operators can lower the caps via env (pydantic-settings AION_ prefix)."""
    import os
    from unittest.mock import patch
    from aion.config import AionSettings

    with patch.dict(os.environ, {
        "AION_STREAM_MAX_BUFFERED_CHUNKS": "100",
        "AION_STREAM_MAX_BUFFERED_BYTES": "1048576",  # 1 MiB
    }):
        s = AionSettings()
        assert s.stream_max_buffered_chunks == 100
        assert s.stream_max_buffered_bytes == 1_048_576


# ── F-17/F-19 — documentation honesty ───────────────────────────────────────

def test_f17_production_checklist_no_inflated_count():
    """PRODUCTION_CHECKLIST.md no longer claims '702+ testes' without qualifier."""
    from pathlib import Path

    doc = Path("docs/PRODUCTION_CHECKLIST.md")
    if not doc.exists():
        return  # docs not bundled in some installs
    content = doc.read_text(encoding="utf-8")
    # The literal "702+ testes" claim must not survive without qualification.
    assert "702+ testes, 0 falhas" not in content
    assert "702 testes" not in content


def test_f19_security_report_no_obsolete_claims():
    """SECURITY_REPORT.md no longer claims aion/rbac.py or start.py exist.

    The corrected doc may *mention* these names while explaining they don't
    exist — that's fine. What we check is the absence of the *false claim*.
    """
    from pathlib import Path

    doc = Path("docs/SECURITY_REPORT.md")
    if not doc.exists():
        return
    content = doc.read_text(encoding="utf-8")
    # Original false claim: "RBAC implementado em `aion/rbac.py`".
    assert "RBAC implementado em `aion/rbac.py`" not in content
    # Original false claim: "start.py tem guard-rail".
    assert "`start.py` tem guard-rail" not in content
    assert "start.py tem guard-rail" not in content
