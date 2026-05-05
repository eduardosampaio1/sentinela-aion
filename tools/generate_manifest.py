#!/usr/bin/env python3
"""Sentinela Artifact Signing — Generate AION Integrity Manifest.

Generates integrity_manifest.json signed with the Sentinela Artifact
Signing Key (Ed25519). Run this at build time (CI/CD), before the Docker
image is assembled.

Usage:
    python tools/generate_manifest.py \\
        --build-id build_20260427_abc \\
        --aion-version 0.2.0 \\
        --artifact-key tools/keys/artifact_private.pem \\
        --out aion/trust_guard/integrity_manifest.json

If --artifact-key is omitted, the manifest is written without a signature
(useful for dev/test environments where signature verification is skipped).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Single source of truth for the critical-file registry. critical_files.py is
# standalone (no aion.* imports) so this script can run in a CI step that
# has not installed the AION package.
from aion.trust_guard.critical_files import resolve_files as _resolve_critical_files


def _hash_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sign_manifest(payload_dict: dict, key_path: Path) -> str:
    """Sign the manifest payload with Ed25519. Returns hex signature."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("ERRO: dependências ausentes. Execute: pip install cryptography", file=sys.stderr)
        sys.exit(1)

    private_key = load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        print("ERRO: a chave de artefato deve ser Ed25519.", file=sys.stderr)
        sys.exit(1)

    payload_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
    signature = private_key.sign(payload_bytes)
    return signature.hex()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera manifest de integridade assinado pelo Sentinela Artifact Signing Key.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--build-id",
        default=f"build_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
        help="Build identifier (default: auto-generated)",
    )
    parser.add_argument(
        "--aion-version",
        default="",
        help="AION semantic version (default: read from aion/__init__.py)",
    )
    parser.add_argument(
        "--artifact-key",
        default="",
        help="Path to Sentinela Artifact Signing Key (Ed25519 private PEM). "
             "If omitted, manifest is unsigned (dev only).",
    )
    parser.add_argument(
        "--out",
        default=str(_ROOT / "aion" / "trust_guard" / "integrity_manifest.json"),
        help="Output path (default: aion/trust_guard/integrity_manifest.json)",
    )
    parser.add_argument(
        "--files-root",
        default=str(_ROOT),
        help="Root directory for resolving critical file paths (default: project root)",
    )

    args = parser.parse_args()

    # Resolve aion_version
    aion_version = args.aion_version
    if not aion_version:
        try:
            init_path = _ROOT / "aion" / "__init__.py"
            for line in init_path.read_text(encoding="utf-8").splitlines():
                if "__version__" in line and "=" in line:
                    aion_version = line.split("=")[1].strip().strip("\"'")
                    break
        except Exception:
            aion_version = "unknown"

    files_root = Path(args.files_root)

    # Resolve the registered patterns into concrete files. The resolver only
    # returns paths that exist on disk, so glob patterns covering features
    # not yet present (e.g. aion/marketplace/*.py while the module is empty)
    # contribute zero entries instead of MISSING markers.
    critical_files = _resolve_critical_files(files_root)

    # Compute per-file hashes
    files: dict[str, str] = {}
    missing: list[str] = []
    for rel in critical_files:
        h = _hash_file(files_root / rel)
        files[rel] = h
        if h == "MISSING":
            missing.append(rel)
            print(f"AVISO: arquivo crítico ausente: {rel}", file=sys.stderr)

    # Build manifest payload (without signature)
    payload: dict = {
        "schema_version": "1.0",
        "build_id": args.build_id,
        "aion_version": aion_version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }

    # Sign if key is provided
    signature = ""
    if args.artifact_key:
        key_path = Path(args.artifact_key)
        if not key_path.exists():
            print(f"ERRO: chave de artefato não encontrada em {key_path}", file=sys.stderr)
            sys.exit(1)
        signature = _sign_manifest(payload, key_path)
        print(f"  Manifesto assinado com {key_path.name}")
    else:
        print("  AVISO: manifest gerado sem assinatura (dev only). "
              "Forneça --artifact-key para produção.", file=sys.stderr)

    manifest = {**payload, "signature": signature}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("  Sentinela Artifact Manifest")
    print("  " + "-" * 50)
    print(f"  Build ID      : {args.build_id}")
    print(f"  AION Version  : {aion_version}")
    print(f"  Files hashed  : {len(files)} ({len(missing)} missing)")
    print(f"  Signed        : {'yes' if signature else 'no (dev)'}")
    print(f"  Output        : {out_path}")
    print("  " + "-" * 50)
    print()

    if missing:
        print(f"AVISO: {len(missing)} arquivo(s) crítico(s) ausente(s). "
              "Verifique o build antes de distribuir.", file=sys.stderr)


if __name__ == "__main__":
    main()
