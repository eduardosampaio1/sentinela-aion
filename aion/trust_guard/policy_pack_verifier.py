"""AION Trust Guard — Policy Pack Verifier (Fase 3).

Verifies externally-distributed policy packs signed by the Sentinela
Policy Pack Signing Key. The bundled catalog (config/collective/
collective_policies.yaml) is trusted via Docker image signing (cosign)
and the integrity manifest — it does not need separate pack verification.

Policy pack format (JSON):
  {
    "schema_version": "1.0",
    "pack_id":         "pack_banking_v2",
    "name":            "Banking Compliance Pack v2",
    "publisher":       "Sentinela Editorial",
    "published_at":    "2026-04-27T00:00:00Z",
    "policies":        [ { ...CollectivePolicy fields... }, ... ],
    "signature":       "<ed25519 hex over canonical payload>"
  }

The signed payload is the canonical JSON of the pack dict with the
"signature" key removed, keys sorted, no whitespace — same convention as
the integrity manifest.

Key hierarchy:
  Sentinela License Signing Key    — licenses (JWT)
  Sentinela Artifact Signing Key   — Docker image integrity manifests
  Sentinela Policy Pack Signing Key — external policy packs  ← this file

Each key rotates independently. The public key is embedded in AION via
AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY env var (PEM). If the env var is
not set, signature verification is skipped (dev/test mode).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aion.trust_guard")


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class PolicyPackResult:
    verified: bool
    pack_id: str = ""
    name: str = ""
    publisher: str = ""
    published_at: str = ""
    policies: list[dict] = field(default_factory=list)
    policy_count: int = 0
    reason: str = ""


# ── Public API ────────────────────────────────────────────────────────────────

def verify_policy_pack(pack_path: Path) -> PolicyPackResult:
    """Load and verify a signed policy pack file.

    Returns PolicyPackResult(verified=True, policies=[...]) on success.
    Returns PolicyPackResult(verified=False, reason=...) on any failure.
    Never raises.
    """
    if not pack_path.exists():
        return PolicyPackResult(verified=False, reason="pack_file_missing")

    try:
        raw = pack_path.read_bytes()
        pack = json.loads(raw)
    except Exception as e:
        return PolicyPackResult(verified=False, reason=f"pack_parse_error: {e}")

    pack_id      = pack.get("pack_id", "")
    name         = pack.get("name", "")
    publisher    = pack.get("publisher", "")
    published_at = pack.get("published_at", "")
    policies     = pack.get("policies", [])
    signature    = pack.get("signature", "")

    if not isinstance(policies, list):
        return PolicyPackResult(
            verified=False, pack_id=pack_id,
            reason="pack_policies_field_invalid",
        )

    sig_ok = _verify_pack_signature(pack, signature)
    if not sig_ok:
        return PolicyPackResult(
            verified=False, pack_id=pack_id,
            reason="pack_signature_invalid",
        )

    return PolicyPackResult(
        verified=True,
        pack_id=pack_id,
        name=name,
        publisher=publisher,
        published_at=published_at,
        policies=policies,
        policy_count=len(policies),
    )


def verify_policy_pack_bytes(raw: bytes) -> PolicyPackResult:
    """Verify a policy pack from raw bytes (e.g. downloaded via API)."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(raw)
        tmp_path = Path(f.name)
    try:
        return verify_policy_pack(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


# ── Signature verification ────────────────────────────────────────────────────

def _verify_pack_signature(pack: dict, signature_hex: str) -> bool:
    """Verify Ed25519 signature over the policy pack.

    Payload: canonical JSON of pack dict without 'signature' key, sorted keys.
    Uses AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY env var (PEM).
    Returns True when key not configured (dev mode — same convention as manifest).
    """
    if not signature_hex:
        logger.debug("trust_guard: policy pack has no signature field")
        return False

    public_key_pem = _get_policy_pack_public_key()
    if not public_key_pem:
        # No key configured — skip check (dev mode)
        logger.debug("trust_guard: no policy pack public key configured, skipping signature")
        return True

    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature

        pub_key = load_pem_public_key(public_key_pem.encode())
        if not isinstance(pub_key, Ed25519PublicKey):
            logger.debug("trust_guard: policy pack key is not Ed25519")
            return False

        payload_dict = {k: v for k, v in pack.items() if k != "signature"}
        payload_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
        sig_bytes = bytes.fromhex(signature_hex)

        pub_key.verify(sig_bytes, payload_bytes)
        return True

    except InvalidSignature:
        logger.debug("trust_guard: policy pack signature verification failed")
        return False
    except Exception as e:
        logger.debug("trust_guard: policy pack signature error: %s", e)
        return False


def _get_policy_pack_public_key() -> str:
    """Return the Sentinela Policy Pack Signing Key public key PEM."""
    import os
    # Env override takes precedence; fall back to TrustGuardSettings
    env_key = os.environ.get("AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY", "").strip()
    if env_key:
        return env_key
    try:
        from aion.config import get_trust_guard_settings
        return get_trust_guard_settings().policy_pack_public_key.strip()
    except Exception:
        return ""


# ── Pack builder (CI / Sentinela Editorial tooling) ──────────────────────────

def build_pack(
    pack_id: str,
    name: str,
    publisher: str,
    published_at: str,
    policies: list[dict],
    private_key_pem: Optional[str] = None,
) -> dict:
    """Build a signed policy pack dict (used by Sentinela Editorial tooling).

    If private_key_pem is None, the pack is built unsigned (signature="").
    The caller must write the result as JSON.
    """
    pack = {
        "schema_version": "1.0",
        "pack_id": pack_id,
        "name": name,
        "publisher": publisher,
        "published_at": published_at,
        "policies": policies,
        "signature": "",
    }

    if private_key_pem:
        payload_dict = {k: v for k, v in pack.items() if k != "signature"}
        payload_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            priv = load_pem_private_key(private_key_pem.encode(), password=None)
            if not isinstance(priv, Ed25519PrivateKey):
                raise ValueError("private key is not Ed25519")
            sig = priv.sign(payload_bytes)
            pack["signature"] = sig.hex()
        except Exception as e:
            raise RuntimeError(f"Failed to sign policy pack: {e}") from e

    return pack
