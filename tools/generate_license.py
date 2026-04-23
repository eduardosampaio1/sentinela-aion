#!/usr/bin/env python3
"""Emissor de licenças AION.

Uso:
    python tools/generate_license.py \\
        --tenant banco-xpto \\
        --issued-to "Banco XPTO S.A." \\
        --days 365 \\
        --tier standard \\
        --features nomos,metis_advanced,analytics \\
        --env prod \\
        --out aion.lic

A chave privada deve estar em tools/keys/private.pem (nunca commitar).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ── Garante que o path do projeto está no sys.path ──
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emite licença AION assinada com EdDSA (Ed25519).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tenant",    required=True, help="ID do tenant/empresa (ex: banco-xpto)")
    parser.add_argument("--issued-to", required=True, help="Nome legível da empresa (ex: 'Banco XPTO S.A.')")
    parser.add_argument("--days",      type=int, default=365, help="Validade em dias (default: 365)")
    parser.add_argument("--tier",      default="standard", choices=["poc","standard","enterprise"],
                        help="Tier da licença (default: standard)")
    parser.add_argument("--env",       default="prod", choices=["poc","staging","prod"],
                        help="Ambiente (default: prod)")
    parser.add_argument("--features",  default="",
                        help="Features separadas por vírgula (vazio = todas). Ex: nomos,metis_advanced")
    parser.add_argument("--key",       default=str(_ROOT / "tools" / "keys" / "private.pem"),
                        help="Caminho da chave privada (default: tools/keys/private.pem)")
    parser.add_argument("--out",       default="aion.lic",
                        help="Arquivo de saída (default: aion.lic)")

    args = parser.parse_args()

    # Load private key
    key_path = Path(args.key)
    if not key_path.exists():
        print(f"ERRO: chave privada não encontrada em {key_path}", file=sys.stderr)
        print("Execute primeiro: python tools/generate_keys.py", file=sys.stderr)
        sys.exit(1)

    try:
        import jwt as pyjwt
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError:
        print("ERRO: dependências ausentes. Execute: pip install PyJWT cryptography", file=sys.stderr)
        sys.exit(1)

    private_key = load_pem_private_key(key_path.read_bytes(), password=None)

    now = int(time.time())
    exp = now + (args.days * 86400)

    features = [f.strip() for f in args.features.split(",") if f.strip()]

    claims: dict = {
        "iss": "baluarte",
        "sub": args.tenant,
        "issued_to": args.issued_to,
        "iat": now,
        "nbf": now,
        "exp": exp,
        "tier": args.tier,
        "env": args.env,
    }
    if features:
        claims["features"] = features

    token = pyjwt.encode(claims, private_key, algorithm="EdDSA")

    out_path = Path(args.out)
    out_path.write_text(token, encoding="utf-8")

    # Summary
    from datetime import datetime, timezone
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d")

    import sys as _sys
    out = _sys.stdout
    print(file=out)
    print("  AION -- Licenca Emitida", file=out)
    print("  " + "-" * 54, file=out)
    print(f"  Tenant    : {args.tenant}", file=out)
    print(f"  Empresa   : {args.issued_to}", file=out)
    print(f"  Tier      : {args.tier}", file=out)
    print(f"  Ambiente  : {args.env}", file=out)
    print(f"  Features  : {', '.join(features) if features else 'todas'}", file=out)
    print(f"  Expira em : {exp_dt}", file=out)
    print(f"  Arquivo   : {out_path}", file=out)
    print("  " + "-" * 54, file=out)
    print("  Entregue o arquivo ao cliente com:", file=out)
    print(f"    AION_LICENSE_PATH={out_path}", file=out)
    print("  ou cole o JWT em:", file=out)
    print("    AION_LICENSE=<conteudo do arquivo>", file=out)
    print(file=out)


if __name__ == "__main__":
    main()
