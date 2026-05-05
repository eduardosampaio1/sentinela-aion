"""Tests for AION Trust Guard — Fase 1 + 2 + 3."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_manifest(path: Path, files_root: Path, extra_files: Optional[dict] = None,
                    signature: str = "aabbcc", build_id: str = "build_test") -> dict:
    """Write a syntactically valid manifest to path. Uses real file hashes."""
    from aion.trust_guard.integrity_manifest import _CRITICAL_FILES
    files = {}
    for rel in _CRITICAL_FILES:
        abs_path = files_root / rel
        if abs_path.exists():
            files[rel] = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        else:
            files[rel] = "MISSING"
    if extra_files:
        files.update(extra_files)
    manifest = {
        "schema_version": "1.0",
        "build_id": build_id,
        "aion_version": "0.0.0",
        "built_at": "2026-01-01T00:00:00Z",
        "files": files,
        "signature": signature,
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


# ══════════════════════════════════════════════════════════════════════════════
# TestTrustState
# ══════════════════════════════════════════════════════════════════════════════

class TestTrustState:
    def test_load_default_when_file_absent(self, tmp_path):
        with patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            from aion.trust_guard.trust_state import load_trust_state, TrustStates
            state = load_trust_state()
        assert state.trust_state == TrustStates.ACTIVE
        assert state.license_id == ""
        assert state.integrity_status == "UNVERIFIED"

    def test_save_load_roundtrip(self, tmp_path):
        with patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            from aion.trust_guard.trust_state import (
                TrustState, TrustStates, save_trust_state, load_trust_state,
            )
            original = TrustState(
                trust_state=TrustStates.ACTIVE,
                license_id="lic_123",
                tenant_id="acme",
                build_id="build_abc",
                heartbeat_required=True,
                grace_hours_remaining=5.0,
            )
            save_trust_state(original)
            restored = load_trust_state()

        assert restored.license_id == "lic_123"
        assert restored.tenant_id == "acme"
        assert restored.build_id == "build_abc"
        assert restored.heartbeat_required is True
        assert restored.grace_hours_remaining == 5.0
        assert restored.persisted_at > 0

    def test_corrupt_json_returns_default(self, tmp_path):
        state_file = tmp_path / "trust_state.json"
        state_file.write_text("{not valid json{{{{", encoding="utf-8")
        with patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            from aion.trust_guard.trust_state import load_trust_state, TrustStates
            state = load_trust_state()
        assert state.trust_state == TrustStates.ACTIVE  # default, no exception

    def test_valid_transitions(self):
        from aion.trust_guard.trust_state import TrustStates
        assert TrustStates.can_transition(TrustStates.ACTIVE, TrustStates.GRACE)
        assert TrustStates.can_transition(TrustStates.ACTIVE, TrustStates.TAMPERED)
        assert TrustStates.can_transition(TrustStates.GRACE, TrustStates.RESTRICTED)
        assert TrustStates.can_transition(TrustStates.RESTRICTED, TrustStates.EXPIRED)
        assert TrustStates.can_transition(TrustStates.EXPIRED, TrustStates.ACTIVE)

    def test_invalid_transitions(self):
        from aion.trust_guard.trust_state import TrustStates
        assert not TrustStates.can_transition(TrustStates.TAMPERED, TrustStates.ACTIVE)
        assert not TrustStates.can_transition(TrustStates.INVALID, TrustStates.ACTIVE)
        assert not TrustStates.can_transition(TrustStates.EXPIRED, TrustStates.TAMPERED)
        assert not TrustStates.can_transition(TrustStates.ACTIVE, TrustStates.RESTRICTED)

    def test_to_dict_from_dict_roundtrip(self):
        from aion.trust_guard.trust_state import TrustState, TrustStates
        s = TrustState(trust_state=TrustStates.GRACE, license_id="x", grace_hours_remaining=3.5)
        restored = TrustState.from_dict(s.to_dict())
        assert restored.trust_state == TrustStates.GRACE
        assert restored.grace_hours_remaining == 3.5

    def test_from_dict_ignores_unknown_keys(self):
        from aion.trust_guard.trust_state import TrustState
        data = {"trust_state": "ACTIVE", "unknown_future_field": "ignored"}
        state = TrustState.from_dict(data)
        assert state.trust_state == "ACTIVE"

    def test_is_operational(self):
        from aion.trust_guard.trust_state import TrustState, TrustStates
        assert TrustState(trust_state=TrustStates.ACTIVE).is_operational()
        assert not TrustState(trust_state=TrustStates.GRACE).is_operational()
        assert not TrustState(trust_state=TrustStates.TAMPERED).is_operational()

    def test_is_degraded(self):
        from aion.trust_guard.trust_state import TrustState, TrustStates
        assert TrustState(trust_state=TrustStates.RESTRICTED).is_degraded()
        assert TrustState(trust_state=TrustStates.EXPIRED).is_degraded()
        assert TrustState(trust_state=TrustStates.TAMPERED).is_degraded()
        assert TrustState(trust_state=TrustStates.INVALID).is_degraded()
        assert not TrustState(trust_state=TrustStates.ACTIVE).is_degraded()
        assert not TrustState(trust_state=TrustStates.GRACE).is_degraded()


# ══════════════════════════════════════════════════════════════════════════════
# TestIntegrityManifest
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrityManifest:
    """All tests run without an artifact public key (dev mode — signature check skipped)."""

    @pytest.fixture(autouse=True)
    def _no_artifact_key(self):
        with patch.dict(os.environ, {"AION_TRUST_GUARD_ARTIFACT_PUBLIC_KEY": ""}):
            yield

    def test_manifest_absent_returns_tampered(self, tmp_path):
        from aion.trust_guard.integrity_manifest import verify_manifest
        result = verify_manifest(manifest_path=tmp_path / "nonexistent.json")
        assert not result.verified
        assert result.reason == "manifest_missing"

    def test_valid_manifest_returns_verified(self, tmp_path):
        # P1.A: paths in the registry are relative to the project root
        # (e.g. "aion/license.py"), not the aion/ package. The helper now
        # receives _PROJECT_ROOT.
        from aion.trust_guard.integrity_manifest import verify_manifest, _PROJECT_ROOT
        manifest_path = tmp_path / "manifest.json"
        _write_manifest(manifest_path, _PROJECT_ROOT)
        result = verify_manifest(manifest_path=manifest_path)
        assert result.verified
        assert result.build_id == "build_test"

    def test_missing_signature_returns_tampered(self, tmp_path):
        from aion.trust_guard.integrity_manifest import verify_manifest, _PROJECT_ROOT
        manifest_path = tmp_path / "manifest.json"
        _write_manifest(manifest_path, _PROJECT_ROOT, signature="")  # empty signature
        result = verify_manifest(manifest_path=manifest_path)
        assert not result.verified
        assert "signature" in result.reason

    def test_altered_file_hash_returns_tampered(self, tmp_path):
        from aion.trust_guard.integrity_manifest import (
            verify_manifest, _PROJECT_ROOT, _CRITICAL_FILES,
        )
        manifest_path = tmp_path / "manifest.json"
        _write_manifest(manifest_path, _PROJECT_ROOT)

        # Corrupt one hash in the manifest
        manifest = json.loads(manifest_path.read_text())
        first_file = _CRITICAL_FILES[0]
        manifest["files"][first_file] = "a" * 64  # wrong hash
        manifest_path.write_text(json.dumps(manifest))

        result = verify_manifest(manifest_path=manifest_path)
        assert not result.verified
        assert first_file in result.files_diverged
        assert result.reason == "files_hash_mismatch"

    def test_corrupt_manifest_json_returns_error(self, tmp_path):
        from aion.trust_guard.integrity_manifest import verify_manifest
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("{bad json{{", encoding="utf-8")
        result = verify_manifest(manifest_path=manifest_path)
        assert not result.verified
        assert "parse_error" in result.reason

    def test_signature_fails_when_key_is_not_ed25519(self, tmp_path):
        from aion.trust_guard.integrity_manifest import verify_manifest, _PROJECT_ROOT
        manifest_path = tmp_path / "manifest.json"
        _write_manifest(manifest_path, _PROJECT_ROOT)

        # Provide a real PEM key that is RSA (not Ed25519) — should return False
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PublicFormat,
            )
            rsa_key = rsa.generate_private_key(65537, 2048)
            pem = rsa_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
        except ImportError:
            pytest.skip("cryptography not installed")

        with patch.dict(os.environ, {"AION_TRUST_GUARD_ARTIFACT_PUBLIC_KEY": pem}):
            result = verify_manifest(manifest_path=manifest_path)
        assert not result.verified

    def test_multiple_diverged_files_all_listed(self, tmp_path):
        from aion.trust_guard.integrity_manifest import (
            verify_manifest, _PROJECT_ROOT, _CRITICAL_FILES,
        )
        manifest_path = tmp_path / "manifest.json"
        _write_manifest(manifest_path, _PROJECT_ROOT)

        manifest = json.loads(manifest_path.read_text())
        for rel in _CRITICAL_FILES[:3]:
            manifest["files"][rel] = "b" * 64
        manifest_path.write_text(json.dumps(manifest))

        result = verify_manifest(manifest_path=manifest_path)
        assert not result.verified
        assert len(result.files_diverged) == 3


# ══════════════════════════════════════════════════════════════════════════════
# TestEntitlementEngine
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _FakeModuleStatus:
    healthy: bool = True
    consecutive_failures: int = 0
    failure_threshold: int = 3


def _make_pipeline(*module_names: str):
    """Create a minimal mock pipeline with the given module names."""
    pipeline = MagicMock()
    pipeline._module_status = {name: _FakeModuleStatus() for name in module_names}
    return pipeline


ALL_MODULES = ("estixe", "nomos", "metis", "metis_post")


class TestEntitlementEngine:
    @pytest.fixture(autouse=True)
    def _reset_nemos_freeze(self):
        yield
        try:
            from aion.nemos import unfreeze_nemos_writes
            unfreeze_nemos_writes()
        except Exception:
            pass

    def test_active_restores_all_modules(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine, TrustViolationBehavior
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        for name in ALL_MODULES:
            pipeline._module_status[name].healthy = False

        state = TrustState(trust_state=TrustStates.ACTIVE)
        EntitlementEngine.apply(pipeline, state)

        for name in ALL_MODULES:
            assert pipeline._module_status[name].healthy, f"{name} should be healthy"

    def test_grace_has_no_functional_impact(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.GRACE)
        EntitlementEngine.apply(pipeline, state)

        for name in ALL_MODULES:
            assert pipeline._module_status[name].healthy, f"{name} should be unaffected in GRACE"

    def test_restricted_freezes_nemos_keeps_modules(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine
        from aion.trust_guard.trust_state import TrustState, TrustStates
        from aion.nemos import _nemos_writes_frozen as _before
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.RESTRICTED)
        EntitlementEngine.apply(pipeline, state)

        import aion.nemos as nemos_mod
        assert nemos_mod._nemos_writes_frozen is True
        # ESTIXE must stay healthy in RESTRICTED
        assert pipeline._module_status["estixe"].healthy

    def test_expired_disables_nomos_and_metis(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.EXPIRED)
        EntitlementEngine.apply(pipeline, state)

        assert not pipeline._module_status["nomos"].healthy
        assert not pipeline._module_status["metis"].healthy
        assert not pipeline._module_status["metis_post"].healthy
        assert pipeline._module_status["estixe"].healthy  # ESTIXE preserved

    def test_tampered_passthrough_disables_all_protected(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine, TrustViolationBehavior
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.TAMPERED)
        EntitlementEngine.apply(pipeline, state, TrustViolationBehavior.PASSTHROUGH)

        for name in ALL_MODULES:
            assert not pipeline._module_status[name].healthy, f"{name} should be off"

    def test_tampered_health_only_raises(self):
        from aion.trust_guard.entitlement_engine import (
            EntitlementEngine, TrustViolationBehavior, TrustViolationError,
        )
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.TAMPERED)

        with pytest.raises(TrustViolationError) as exc_info:
            EntitlementEngine.apply(pipeline, state, TrustViolationBehavior.HEALTH_ONLY)
        assert exc_info.value.trust_state == TrustStates.TAMPERED

    def test_invalid_passthrough_disables_all_protected(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine, TrustViolationBehavior
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.INVALID)
        EntitlementEngine.apply(pipeline, state, TrustViolationBehavior.PASSTHROUGH)

        for name in ALL_MODULES:
            assert not pipeline._module_status[name].healthy

    def test_invalid_health_only_raises(self):
        from aion.trust_guard.entitlement_engine import (
            EntitlementEngine, TrustViolationBehavior, TrustViolationError,
        )
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.INVALID)

        with pytest.raises(TrustViolationError):
            EntitlementEngine.apply(pipeline, state, TrustViolationBehavior.HEALTH_ONLY)

    def test_apply_is_idempotent(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.EXPIRED)

        EntitlementEngine.apply(pipeline, state)
        first_state = {n: pipeline._module_status[n].healthy for n in ALL_MODULES}
        EntitlementEngine.apply(pipeline, state)
        second_state = {n: pipeline._module_status[n].healthy for n in ALL_MODULES}

        assert first_state == second_state

    def test_absent_module_is_noop(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine
        from aion.trust_guard.trust_state import TrustState, TrustStates
        # Pipeline with only estixe — nomos/metis absent
        pipeline = _make_pipeline("estixe")
        state = TrustState(trust_state=TrustStates.EXPIRED)
        # Must not raise
        EntitlementEngine.apply(pipeline, state)
        assert pipeline._module_status["estixe"].healthy  # ESTIXE unaffected by EXPIRED

    def test_disabled_module_has_failure_count_at_threshold(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)
        state = TrustState(trust_state=TrustStates.EXPIRED)
        EntitlementEngine.apply(pipeline, state)

        nomos_status = pipeline._module_status["nomos"]
        from aion.config import get_settings
        assert nomos_status.consecutive_failures >= get_settings().module_failure_threshold

    def test_restore_active_zeroes_failure_count(self):
        from aion.trust_guard.entitlement_engine import EntitlementEngine
        from aion.trust_guard.trust_state import TrustState, TrustStates
        pipeline = _make_pipeline(*ALL_MODULES)

        # First degrade
        EntitlementEngine.apply(pipeline, TrustState(trust_state=TrustStates.EXPIRED))
        # Then restore
        EntitlementEngine.apply(pipeline, TrustState(trust_state=TrustStates.ACTIVE))

        for name in ALL_MODULES:
            assert pipeline._module_status[name].consecutive_failures == 0
            assert pipeline._module_status[name].healthy


# ══════════════════════════════════════════════════════════════════════════════
# TestLicenseAuthority
# ══════════════════════════════════════════════════════════════════════════════

def _mock_license(
    tenant: str = "acme",
    tier: str = "poc",
    state_val: str = "active",
    expires_at: float = 0.0,
    features: Optional[list] = None,
    env: str = "prod",
):
    from aion.license import LicenseInfo, LicenseState
    state_map = {
        "active": LicenseState.ACTIVE,
        "grace": LicenseState.GRACE,
        "expired": LicenseState.EXPIRED,
        "invalid": LicenseState.INVALID,
    }
    lic = MagicMock(spec=LicenseInfo)
    lic.tenant = tenant
    lic.tier = tier
    lic.state = state_map.get(state_val, LicenseState.ACTIVE)
    lic.expires_at = expires_at or (time.time() + 30 * 24 * 3600)
    lic.features = features or []
    lic.env = env
    return lic


class TestLicenseAuthority:
    def test_extracts_standard_claims(self):
        from aion.trust_guard.license_authority import get_license_claims
        lic = _mock_license(tenant="banco-inter", tier="enterprise")
        raw = {"license_id": "lic_abc", "heartbeat_required": True,
               "heartbeat_url": "https://sentinela.io/hb", "min_aion_version": "0.2.0"}

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic), \
             patch("aion.trust_guard.license_authority._get_raw_claims", return_value=raw):
            claims = get_license_claims()

        assert claims["license_id"] == "lic_abc"
        assert claims["tenant_id"] == "banco-inter"
        assert claims["tier"] == "enterprise"
        assert claims["heartbeat_required"] is True
        assert claims["heartbeat_url"] == "https://sentinela.io/hb"
        assert claims["min_aion_version"] == "0.2.0"

    def test_optional_claims_absent_return_defaults(self):
        from aion.trust_guard.license_authority import get_license_claims
        lic = _mock_license()

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic), \
             patch("aion.trust_guard.license_authority._get_raw_claims", return_value={}):
            claims = get_license_claims()

        assert claims["heartbeat_required"] is False
        assert claims["heartbeat_url"] == ""
        assert claims["min_aion_version"] == ""
        assert claims["features"] == []
        assert claims["license_id"] == ""  # no jti either

    def test_heartbeat_required_defaults_false(self):
        from aion.trust_guard.license_authority import get_license_claims
        lic = _mock_license()

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic), \
             patch("aion.trust_guard.license_authority._get_raw_claims", return_value={}):
            claims = get_license_claims()

        assert claims["heartbeat_required"] is False

    def test_license_invalid_state_maps_to_trust_invalid(self):
        from aion.trust_guard.license_authority import determine_license_state
        from aion.trust_guard.trust_state import TrustStates
        lic = _mock_license(state_val="invalid")

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            trust_state, reason = determine_license_state({})

        assert trust_state == TrustStates.INVALID
        assert "invalid" in reason

    def test_license_expired_maps_to_trust_expired(self):
        from aion.trust_guard.license_authority import determine_license_state
        from aion.trust_guard.trust_state import TrustStates
        lic = _mock_license(state_val="expired")

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            trust_state, reason = determine_license_state({})

        assert trust_state == TrustStates.EXPIRED

    def test_license_grace_maps_to_trust_grace(self):
        from aion.trust_guard.license_authority import determine_license_state
        from aion.trust_guard.trust_state import TrustStates
        lic = _mock_license(state_val="grace")

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            trust_state, reason = determine_license_state({})

        assert trust_state == TrustStates.GRACE

    def test_active_license_expiring_soon_maps_to_grace(self):
        from aion.trust_guard.license_authority import determine_license_state
        from aion.trust_guard.trust_state import TrustStates
        from aion.license import LicenseState
        lic = _mock_license(state_val="active")
        lic.state = LicenseState.ACTIVE
        # Expires in 3 days (< 7d threshold)
        expires_soon = time.time() + 3 * 24 * 3600

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            trust_state, reason = determine_license_state({"expires_at": expires_soon})

        assert trust_state == TrustStates.GRACE
        assert "expiring_soon" in reason

    def test_build_initial_trust_state_sets_fields(self):
        from aion.trust_guard.license_authority import build_initial_trust_state
        from aion.trust_guard.trust_state import TrustStates, IntegrityStatus
        from aion.license import LicenseState
        lic = _mock_license(tenant="t1", state_val="active")
        lic.state = LicenseState.ACTIVE
        expires_at = time.time() + 60 * 24 * 3600  # 60 days out — well beyond 7d grace
        claims = {
            "license_id": "lic_xyz",
            "tenant_id": "t1",
            "expires_at": expires_at,
            "heartbeat_required": False,
        }

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            state = build_initial_trust_state(claims, build_id="build_001", aion_version="0.2.0")

        assert state.trust_state == TrustStates.ACTIVE
        assert state.license_id == "lic_xyz"
        assert state.build_id == "build_001"
        assert state.aion_version == "0.2.0"
        assert state.integrity_status == IntegrityStatus.UNVERIFIED
        assert state.grace_hours_remaining is None  # not in GRACE

    def test_build_initial_trust_state_grace_has_hours_remaining(self):
        from aion.trust_guard.license_authority import build_initial_trust_state
        from aion.trust_guard.trust_state import TrustStates
        from aion.license import LicenseState
        lic = _mock_license(state_val="grace")
        lic.state = LicenseState.GRACE
        expires_at = time.time() + 4 * 3600  # 4 hours
        claims = {"license_id": "lic_xyz", "tenant_id": "t1", "expires_at": expires_at}

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            state = build_initial_trust_state(claims, build_id="", aion_version="")

        assert state.trust_state == TrustStates.GRACE
        assert state.grace_hours_remaining is not None
        assert 0 < state.grace_hours_remaining <= 4.0

    def test_build_initial_trust_state_stores_heartbeat_url(self):
        """heartbeat_url from JWT claims is stored in TrustState."""
        from aion.trust_guard.license_authority import build_initial_trust_state
        from aion.trust_guard.trust_state import TrustStates
        from aion.license import LicenseState
        lic = _mock_license(state_val="active")
        lic.state = LicenseState.ACTIVE
        expires_at = time.time() + 60 * 24 * 3600
        claims = {
            "license_id": "lic_hb",
            "tenant_id": "acme",
            "expires_at": expires_at,
            "heartbeat_url": "https://sentinela.io/heartbeat",
            "heartbeat_required": True,
        }

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            state = build_initial_trust_state(claims, build_id="", aion_version="")

        assert state.heartbeat_url == "https://sentinela.io/heartbeat"
        assert state.heartbeat_required is True

    def test_heartbeat_url_empty_when_claim_absent(self):
        """Absent heartbeat_url claim → empty string in TrustState."""
        from aion.trust_guard.license_authority import build_initial_trust_state
        from aion.license import LicenseState
        lic = _mock_license(state_val="active")
        lic.state = LicenseState.ACTIVE
        claims = {"expires_at": time.time() + 3600}

        with patch("aion.trust_guard.license_authority.get_license", return_value=lic):
            state = build_initial_trust_state(claims, build_id="", aion_version="")

        assert state.heartbeat_url == ""


class TestGetHeartbeatUrl:
    """Tests for _get_heartbeat_url() priority: env override > JWT claim."""

    def test_env_override_takes_precedence_over_state(self):
        from aion.trust_guard import _get_heartbeat_url
        from aion.trust_guard.trust_state import TrustState
        state = TrustState(heartbeat_url="https://from-jwt.io/hb")

        with patch.dict(os.environ, {"AION_TRUST_GUARD_SERVER_URL": "https://env-override.io/hb"}):
            url = _get_heartbeat_url(state)

        assert url == "https://env-override.io/hb"

    def test_falls_back_to_state_heartbeat_url(self):
        from aion.trust_guard import _get_heartbeat_url
        from aion.trust_guard.trust_state import TrustState
        state = TrustState(heartbeat_url="https://from-jwt.io/hb")

        with patch.dict(os.environ, {"AION_TRUST_GUARD_SERVER_URL": ""}):
            url = _get_heartbeat_url(state)

        assert url == "https://from-jwt.io/hb"

    def test_returns_empty_when_both_absent(self):
        from aion.trust_guard import _get_heartbeat_url
        from aion.trust_guard.trust_state import TrustState
        state = TrustState(heartbeat_url="")

        with patch.dict(os.environ, {"AION_TRUST_GUARD_SERVER_URL": ""}):
            url = _get_heartbeat_url(state)

        assert url == ""

    def test_trust_state_roundtrip_preserves_heartbeat_url(self, tmp_path):
        """heartbeat_url survives save → load cycle."""
        with patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            from aion.trust_guard.trust_state import TrustState, save_trust_state, load_trust_state
            s = TrustState(heartbeat_url="https://sentinela.io/hb")
            save_trust_state(s)
            loaded = load_trust_state()
        assert loaded.heartbeat_url == "https://sentinela.io/hb"


# ══════════════════════════════════════════════════════════════════════════════
# TestNemosFreeze
# ══════════════════════════════════════════════════════════════════════════════

class TestNemosFreeze:
    @pytest.fixture(autouse=True)
    def _reset(self):
        from aion.nemos import unfreeze_nemos_writes
        unfreeze_nemos_writes()
        yield
        unfreeze_nemos_writes()

    def test_freeze_sets_flag(self):
        import aion.nemos as nemos_mod
        from aion.nemos import freeze_nemos_writes
        freeze_nemos_writes()
        assert nemos_mod._nemos_writes_frozen is True

    def test_unfreeze_clears_flag(self):
        import aion.nemos as nemos_mod
        from aion.nemos import freeze_nemos_writes, unfreeze_nemos_writes
        freeze_nemos_writes()
        unfreeze_nemos_writes()
        assert nemos_mod._nemos_writes_frozen is False

    def test_record_outcome_skipped_when_frozen(self):
        from aion.nemos import get_nemos, freeze_nemos_writes
        from aion.nemos.models import OutcomeRecord
        import time as _time
        freeze_nemos_writes()
        nemos = get_nemos()
        record = OutcomeRecord(
            request_id="req1", tenant="t1", timestamp=_time.time(),
            model="gpt-4o-mini", provider="openai", complexity_score=0.5,
            detected_intent="general", estimated_cost=0.001, actual_cost=0.001,
            actual_latency_ms=50.0, actual_prompt_tokens=10, actual_completion_tokens=5,
            success=True, route_reason="test", decision="continue",
        )
        with patch.object(nemos._store, "set_json", new_callable=MagicMock) as mock_set:
            import asyncio
            asyncio.run(nemos.record_outcome(record))
        mock_set.assert_not_called()

    def test_record_economics_skipped_when_frozen(self):
        from aion.nemos import get_nemos, freeze_nemos_writes
        freeze_nemos_writes()
        nemos = get_nemos()
        with patch.object(nemos._store, "set_json", new_callable=MagicMock) as mock_set:
            import asyncio
            asyncio.run(nemos.record_economics(
                "t1", "gpt-4o-mini", "general", "bypass",
                0.001, 0.002, 100, 50.0,
            ))
        mock_set.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# TestHeartbeatReporter (Fase 2)
# ══════════════════════════════════════════════════════════════════════════════

import asyncio as _asyncio


def _run(coro):
    return _asyncio.run(coro)


def _make_state(
    trust_state: str = "ACTIVE",
    tenant_id: str = "acme",
    build_id: str = "build_test",
    aion_version: str = "0.2.0",
    heartbeat_required: bool = False,
    last_heartbeat_at: float = 0.0,
    entitlement_expires_at: float = 0.0,
) -> "TrustState":
    from aion.trust_guard.trust_state import TrustState
    return TrustState(
        trust_state=trust_state,
        tenant_id=tenant_id,
        build_id=build_id,
        aion_version=aion_version,
        heartbeat_required=heartbeat_required,
        last_heartbeat_at=last_heartbeat_at,
        entitlement_expires_at=entitlement_expires_at,
    )


class TestHeartbeatReporter:
    """Tests for HeartbeatReporter.report() — all HTTP calls are mocked."""

    def test_success_updates_trust_state_from_server(self, tmp_path):
        """200 response with trust_state=ACTIVE updates state fields."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        server_response = {
            "trust_state": "ACTIVE",
            "entitlement_expires_at": time.time() + 30 * 24 * 3600,
            "restricted_features": [],
        }
        state = _make_state()

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   return_value=server_response), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb"))

        assert result.trust_state == "ACTIVE"
        assert result.last_heartbeat_success is True
        assert result.last_heartbeat_at > 0

    def test_success_applies_grace_state_from_server(self, tmp_path):
        """Server can downgrade state to GRACE (e.g., license near expiry)."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        expires_soon = time.time() + 5 * 3600
        server_response = {
            "trust_state": "GRACE",
            "entitlement_expires_at": expires_soon,
            "restricted_features": [],
        }
        state = _make_state()

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   return_value=server_response), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb"))

        assert result.trust_state == "GRACE"
        assert result.grace_hours_remaining is not None
        assert 0 < result.grace_hours_remaining <= 5.0

    def test_success_ignores_unknown_server_trust_state(self, tmp_path):
        """Server returns an unrecognised trust_state — current state preserved."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        server_response = {"trust_state": "UNKNOWN_FUTURE_STATE"}
        state = _make_state(trust_state="ACTIVE")

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   return_value=server_response), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb"))

        assert result.trust_state == "ACTIVE"  # unchanged

    def test_network_failure_heartbeat_not_required_no_change(self, tmp_path):
        """Network error + heartbeat_required=False → state unchanged."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        state = _make_state(heartbeat_required=False, trust_state="ACTIVE")

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   side_effect=Exception("connection refused")), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb"))

        assert result.trust_state == "ACTIVE"
        assert result.last_heartbeat_success is False  # (default — never updated)

    def test_network_failure_required_within_grace_stays_active(self, tmp_path):
        """Network error + heartbeat_required=True + last HB within grace → no state change."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        # Last successful HB was 2 hours ago; grace is 48h
        state = _make_state(
            heartbeat_required=True,
            trust_state="ACTIVE",
            last_heartbeat_at=time.time() - 2 * 3600,
        )

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   side_effect=Exception("timeout")), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch("aion.config.get_trust_guard_settings") as mock_cfg, \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            mock_cfg.return_value.grace_hours = 48
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb",
                                                   grace_hours=48))

        assert result.trust_state == "ACTIVE"

    def test_network_failure_required_grace_exhausted_transitions_to_grace(self, tmp_path):
        """Network error + heartbeat_required=True + grace exhausted → transitions to GRACE."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        # Last HB was 50h ago; grace is 48h → exhausted
        state = _make_state(
            heartbeat_required=True,
            trust_state="ACTIVE",
            last_heartbeat_at=time.time() - 50 * 3600,
        )

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   side_effect=Exception("timeout")), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch("aion.config.get_trust_guard_settings") as mock_cfg, \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            mock_cfg.return_value.grace_hours = 48
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb",
                                                   grace_hours=48))

        assert result.trust_state == "GRACE"
        assert result.state_reason == "heartbeat_grace_expired"

    def test_never_heartbeat_before_gives_benefit_of_doubt(self, tmp_path):
        """last_heartbeat_at=0 (first boot) → no state change even with heartbeat_required."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        state = _make_state(
            heartbeat_required=True,
            trust_state="ACTIVE",
            last_heartbeat_at=0.0,  # never attempted
        )

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   side_effect=Exception("timeout")), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb",
                                                   grace_hours=48))

        assert result.trust_state == "ACTIVE"

    def test_server_http_error_treated_as_failure(self, tmp_path):
        """HTTP 500 from server is treated the same as network failure."""
        import httpx
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        state = _make_state(heartbeat_required=False)

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   side_effect=httpx.HTTPStatusError("500", request=MagicMock(),
                                                      response=MagicMock())), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb"))

        assert result.trust_state == "ACTIVE"  # unchanged (heartbeat_required=False)

    def test_restricted_features_updated_from_server(self, tmp_path):
        """Server can push a list of restricted_features into the state."""
        from aion.trust_guard.heartbeat_reporter import HeartbeatReporter
        server_response = {
            "trust_state": "ACTIVE",
            "restricted_features": ["advanced_routing", "metis_compression"],
        }
        state = _make_state()

        with patch("aion.trust_guard.heartbeat_reporter._post_heartbeat",
                   return_value=server_response), \
             patch("aion.trust_guard.trust_state.save_trust_state"), \
             patch.dict(os.environ, {"AION_RUNTIME_DIR": str(tmp_path)}):
            result = _run(HeartbeatReporter.report(state, "https://sentinela.test/hb"))

        assert result.restricted_features == ["advanced_routing", "metis_compression"]

    def test_payload_includes_files_hash(self):
        """Heartbeat payload must include a non-empty files_hash field."""
        from aion.trust_guard.heartbeat_reporter import _build_payload
        state = _make_state()
        payload = _build_payload(state)

        assert "files_hash" in payload
        assert isinstance(payload["files_hash"], str)
        assert "tenant_id" in payload
        assert "build_id" in payload
        assert "aion_version" in payload
        assert "timestamp" in payload


# ══════════════════════════════════════════════════════════════════════════════
# TestMTLS (Fase 3)
# ══════════════════════════════════════════════════════════════════════════════

class TestMTLS:
    """Tests for _build_ssl_context() in heartbeat_reporter."""

    def test_no_env_vars_returns_true(self):
        """Without any mTLS env vars, returns True (httpx default SSL)."""
        from aion.trust_guard.heartbeat_reporter import _build_ssl_context
        with patch.dict(os.environ, {
            "AION_TRUST_GUARD_CLIENT_CERT": "",
            "AION_TRUST_GUARD_CLIENT_KEY": "",
            "AION_TRUST_GUARD_CA_CERT": "",
        }):
            result = _build_ssl_context()
        assert result is True

    def test_ca_cert_only_creates_ssl_context(self, tmp_path):
        """Only CA_CERT set → creates SSL context with custom CA (no client cert)."""
        import ssl
        from aion.trust_guard.heartbeat_reporter import _build_ssl_context

        # Create a self-signed CA cert for testing
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            import datetime

            key = ec.generate_private_key(ec.SECP256R1())
            subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256())
            )
            ca_path = tmp_path / "ca.pem"
            ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        except ImportError:
            pytest.skip("cryptography not installed")

        with patch.dict(os.environ, {
            "AION_TRUST_GUARD_CLIENT_CERT": "",
            "AION_TRUST_GUARD_CLIENT_KEY": "",
            "AION_TRUST_GUARD_CA_CERT": str(ca_path),
        }):
            result = _build_ssl_context()
        assert isinstance(result, ssl.SSLContext)

    def test_only_cert_without_key_does_not_load_chain(self, tmp_path):
        """CLIENT_CERT without CLIENT_KEY → warns but still creates context."""
        import ssl
        from aion.trust_guard.heartbeat_reporter import _build_ssl_context

        fake_cert = tmp_path / "cert.pem"
        fake_cert.write_text("NOT_REAL")

        with patch.dict(os.environ, {
            "AION_TRUST_GUARD_CLIENT_CERT": str(fake_cert),
            "AION_TRUST_GUARD_CLIENT_KEY": "",
            "AION_TRUST_GUARD_CA_CERT": "",
        }):
            # Should not raise; just creates a default context (cert missing key → logged)
            result = _build_ssl_context()
        # Returns an ssl.SSLContext (though chain is not loaded due to missing key)
        assert isinstance(result, ssl.SSLContext)


# ══════════════════════════════════════════════════════════════════════════════
# TestPolicyPackVerifier (Fase 3)
# ══════════════════════════════════════════════════════════════════════════════

def _make_policy_pack(
    tmp_path: Path,
    policies: Optional[list] = None,
    signature: str = "aabbcc",
    pack_id: str = "pack_test",
) -> Path:
    """Write a minimal policy pack JSON file."""
    pack = {
        "schema_version": "1.0",
        "pack_id": pack_id,
        "name": "Test Pack",
        "publisher": "Sentinela Editorial",
        "published_at": "2026-04-27T00:00:00Z",
        "policies": policies or [{"id": "pol_001", "name": "Test Policy"}],
        "signature": signature,
    }
    path = tmp_path / f"{pack_id}.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    return path


class TestPolicyPackVerifier:
    @pytest.fixture(autouse=True)
    def _no_pack_key(self):
        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": ""}):
            yield

    def test_file_missing_returns_error(self, tmp_path):
        from aion.trust_guard.policy_pack_verifier import verify_policy_pack
        result = verify_policy_pack(tmp_path / "nonexistent.json")
        assert not result.verified
        assert result.reason == "pack_file_missing"

    def test_corrupt_json_returns_error(self, tmp_path):
        from aion.trust_guard.policy_pack_verifier import verify_policy_pack
        bad = tmp_path / "bad.json"
        bad.write_text("{not json{{{", encoding="utf-8")
        result = verify_policy_pack(bad)
        assert not result.verified
        assert "parse_error" in result.reason

    def test_missing_signature_returns_error(self, tmp_path):
        from aion.trust_guard.policy_pack_verifier import verify_policy_pack
        path = _make_policy_pack(tmp_path, signature="")
        result = verify_policy_pack(path)
        assert not result.verified
        assert result.reason == "pack_signature_invalid"

    def test_valid_pack_without_key_returns_verified(self, tmp_path):
        """Without a key, any non-empty signature passes (dev mode)."""
        from aion.trust_guard.policy_pack_verifier import verify_policy_pack
        path = _make_policy_pack(tmp_path, signature="deadbeef")
        result = verify_policy_pack(path)
        assert result.verified
        assert result.pack_id == "pack_test"
        assert result.policy_count == 1

    def test_invalid_signature_with_key_fails(self, tmp_path):
        """With a real Ed25519 key configured, wrong signature is rejected."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PublicFormat, NoEncryption, PrivateFormat,
            )
        except ImportError:
            pytest.skip("cryptography not installed")

        from aion.trust_guard.policy_pack_verifier import verify_policy_pack
        priv = Ed25519PrivateKey.generate()
        pub_pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()

        path = _make_policy_pack(tmp_path, signature="badbadbadbad")
        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": pub_pem}):
            result = verify_policy_pack(path)
        assert not result.verified
        assert result.reason == "pack_signature_invalid"

    def test_valid_signature_with_key_passes(self, tmp_path):
        """Round-trip: build_pack signs, verify_policy_pack verifies."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PublicFormat, NoEncryption, PrivateFormat,
            )
        except ImportError:
            pytest.skip("cryptography not installed")

        from aion.trust_guard.policy_pack_verifier import build_pack, verify_policy_pack

        priv = Ed25519PrivateKey.generate()
        priv_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
        pub_pem  = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()

        pack_dict = build_pack(
            pack_id="pack_banking_v1",
            name="Banking Compliance Pack",
            publisher="Sentinela Editorial",
            published_at="2026-04-27T00:00:00Z",
            policies=[{"id": "pol_001", "name": "PII Guard Brazil"}],
            private_key_pem=priv_pem,
        )
        pack_path = tmp_path / "pack.json"
        pack_path.write_text(json.dumps(pack_dict), encoding="utf-8")

        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": pub_pem}):
            result = verify_policy_pack(pack_path)

        assert result.verified
        assert result.pack_id == "pack_banking_v1"
        assert result.policy_count == 1
        assert result.policies[0]["id"] == "pol_001"

    def test_tampered_policies_field_fails(self, tmp_path):
        """Altering policies after signing invalidates the signature."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PublicFormat, NoEncryption, PrivateFormat,
            )
        except ImportError:
            pytest.skip("cryptography not installed")

        from aion.trust_guard.policy_pack_verifier import build_pack, verify_policy_pack

        priv = Ed25519PrivateKey.generate()
        priv_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
        pub_pem  = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()

        pack_dict = build_pack(
            pack_id="pack_test",
            name="Original",
            publisher="Sentinela",
            published_at="2026-04-27T00:00:00Z",
            policies=[{"id": "pol_001"}],
            private_key_pem=priv_pem,
        )
        # Tamper: inject a malicious policy after signing
        pack_dict["policies"].append({"id": "malicious_policy", "name": "EVIL"})
        pack_path = tmp_path / "tampered.json"
        pack_path.write_text(json.dumps(pack_dict), encoding="utf-8")

        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": pub_pem}):
            result = verify_policy_pack(pack_path)
        assert not result.verified

    def test_build_pack_without_key_produces_empty_signature(self):
        from aion.trust_guard.policy_pack_verifier import build_pack
        pack = build_pack(
            pack_id="pack_dev",
            name="Dev Pack",
            publisher="internal",
            published_at="2026-04-27T00:00:00Z",
            policies=[],
            private_key_pem=None,
        )
        assert pack["signature"] == ""
        assert pack["pack_id"] == "pack_dev"

    def test_build_pack_with_non_ed25519_key_raises(self):
        """Trying to sign with RSA key raises RuntimeError."""
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PrivateFormat, NoEncryption,
            )
        except ImportError:
            pytest.skip("cryptography not installed")

        from aion.trust_guard.policy_pack_verifier import build_pack

        rsa_key = rsa.generate_private_key(65537, 2048)
        pem = rsa_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()

        with pytest.raises(RuntimeError, match="not Ed25519"):
            build_pack("p", "n", "pub", "2026", [], private_key_pem=pem)

    def test_verify_bytes_api(self, tmp_path):
        """verify_policy_pack_bytes accepts raw bytes."""
        from aion.trust_guard.policy_pack_verifier import verify_policy_pack_bytes
        raw = json.dumps({
            "schema_version": "1.0",
            "pack_id": "pack_bytes",
            "name": "Bytes Pack",
            "publisher": "test",
            "published_at": "2026-04-27",
            "policies": [],
            "signature": "deadbeef",
        }).encode()
        result = verify_policy_pack_bytes(raw)
        assert result.verified
        assert result.pack_id == "pack_bytes"
