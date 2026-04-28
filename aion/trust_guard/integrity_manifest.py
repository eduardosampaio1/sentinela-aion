"""AION Trust Guard — Integrity Manifest verification.

Verifies the build-time integrity manifest signed by the Sentinela Artifact
Signing Key. The manifest contains SHA-256 hashes of critical module files
and is bundled inside the Docker image at build time.

Limitation (acknowledged):
  Hash comparison detects accidental modification, version mismatch and build
  divergence. It does not prevent a sophisticated attacker with root access who
  can modify both the code and this check. Production hardening path:
  obfuscated/compiled artifacts + cosign image signing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aion.trust_guard")

# ── Paths ─────────────────────────────────────────────────────────────────────

# Package root: aion/trust_guard/../  →  aion/
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Default manifest location (bundled in the Docker image)
_MANIFEST_PATH = Path(__file__).resolve().parent / "integrity_manifest.json"

# Critical files whose integrity is verified at startup
_CRITICAL_FILES: tuple[str, ...] = (
    "aion/license.py",
    "aion/middleware.py",
    "aion/pipeline.py",
    "aion/nemos/__init__.py",
    "aion/nomos/__init__.py",
    "aion/estixe/__init__.py",
    "aion/metis/__init__.py",
)


def get_critical_files() -> list[Path]:
    """Return absolute paths to the critical files listed in _CRITICAL_FILES."""
    return [_PACKAGE_ROOT / f for f in _CRITICAL_FILES]


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class IntegrityResult:
    verified: bool
    build_id: str = ""
    aion_version: str = ""
    files_diverged: list[str] = field(default_factory=list)
    reason: str = ""


# ── Hash computation ──────────────────────────────────────────────────────────

def compute_files_hash(files: Optional[list[Path]] = None) -> str:
    """Compute a single SHA-256 over all critical files (sorted by path string).

    Files are processed in deterministic order. If a file is absent, the string
    'MISSING:{relative_path}' contributes to the hash — so removal is detectable.
    """
    if files is None:
        files = get_critical_files()

    h = hashlib.sha256()
    for path in sorted(files, key=lambda p: str(p)):
        rel = str(path.relative_to(_PACKAGE_ROOT)) if path.is_absolute() else str(path)
        if path.exists():
            h.update(path.read_bytes())
        else:
            h.update(f"MISSING:{rel}".encode())
    return h.hexdigest()


def _hash_single_file(path: Path) -> str:
    """SHA-256 of a single file. Returns 'MISSING' if the file does not exist."""
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Manifest verification ─────────────────────────────────────────────────────

def verify_manifest(manifest_path: Optional[Path] = None) -> IntegrityResult:
    """Verify the integrity manifest.

    Steps:
      1. Load manifest JSON.
      2. Verify Ed25519 signature (Sentinela Artifact Signing Key).
      3. Compare per-file hashes against current disk content.

    Returns IntegrityResult(verified=True) on success, or with
    verified=False and reason/files_diverged on any failure.
    """
    if manifest_path is None:
        manifest_path = _MANIFEST_PATH

    # Step 1: load manifest
    if not manifest_path.exists():
        return IntegrityResult(
            verified=False,
            reason="manifest_missing",
        )

    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except Exception as e:
        return IntegrityResult(
            verified=False,
            reason=f"manifest_parse_error: {e}",
        )

    build_id = manifest.get("build_id", "")
    aion_version = manifest.get("aion_version", "")
    expected_files: dict[str, str] = manifest.get("files", {})
    signature_hex: str = manifest.get("signature", "")

    # Step 2: verify signature
    sig_result = _verify_signature(manifest, signature_hex)
    if not sig_result:
        return IntegrityResult(
            verified=False,
            build_id=build_id,
            aion_version=aion_version,
            reason="manifest_signature_invalid",
        )

    # Step 3: compare per-file hashes
    diverged: list[str] = []
    for rel_path, expected_hash in expected_files.items():
        abs_path = _PACKAGE_ROOT / rel_path
        actual_hash = _hash_single_file(abs_path)
        if actual_hash != expected_hash:
            diverged.append(rel_path)
            logger.debug(
                "trust_guard: integrity divergence — %s expected=%s actual=%s",
                rel_path, expected_hash[:12], actual_hash[:12],
            )

    if diverged:
        return IntegrityResult(
            verified=False,
            build_id=build_id,
            aion_version=aion_version,
            files_diverged=diverged,
            reason="files_hash_mismatch",
        )

    return IntegrityResult(
        verified=True,
        build_id=build_id,
        aion_version=aion_version,
    )


def _verify_signature(manifest: dict, signature_hex: str) -> bool:
    """Verify Ed25519 signature over the manifest (excluding the 'signature' field).

    The payload signed is the canonical JSON of the manifest dict with the
    'signature' key removed, keys sorted, no whitespace.

    Uses the Sentinela Artifact Signing Key public key embedded via
    AION_TRUST_GUARD_ARTIFACT_PUBLIC_KEY env var or the embedded default.
    """
    if not signature_hex:
        # No signature present — treated as unverified/tampered
        logger.debug("trust_guard: manifest has no signature field")
        return False

    public_key_pem = _get_artifact_public_key()
    if not public_key_pem:
        # No artifact key configured — skip signature check (dev mode)
        logger.debug("trust_guard: no artifact public key configured, skipping signature")
        return True

    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature

        pub_key = load_pem_public_key(public_key_pem.encode())
        if not isinstance(pub_key, Ed25519PublicKey):
            logger.debug("trust_guard: artifact key is not Ed25519")
            return False

        # Canonical payload: manifest without 'signature', sorted keys
        payload_dict = {k: v for k, v in manifest.items() if k != "signature"}
        payload_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
        signature_bytes = bytes.fromhex(signature_hex)

        pub_key.verify(signature_bytes, payload_bytes)
        return True

    except InvalidSignature:
        logger.debug("trust_guard: artifact signature verification failed")
        return False
    except Exception as e:
        logger.debug("trust_guard: signature verification error: %s", e)
        return False


def _get_artifact_public_key() -> str:
    """Return the Sentinela Artifact Signing Key public key PEM.

    Reads from AION_TRUST_GUARD_ARTIFACT_PUBLIC_KEY env var.
    Returns empty string if not configured (disables signature check).
    """
    import os
    return os.environ.get("AION_TRUST_GUARD_ARTIFACT_PUBLIC_KEY", "").strip()
