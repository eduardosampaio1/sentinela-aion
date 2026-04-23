"""Configura tenants no AION via API de overrides.

Lê os arquivos YAML em tenants/ e aplica cada configuração via:
    PUT http://localhost:8080/v1/overrides
    Header: X-Aion-Tenant: <tenant_id>

Chamado automaticamente pelo start.py após o AION estar no ar.
Pode ser re-executado a qualquer momento para resetar as configs.

Uso:
    python tenant_init.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml  # PyYAML (disponível no venv do AION)
except ImportError:
    # Fallback manual mínimo para YAML simples (sem deps extras)
    yaml = None

AION_URL    = "http://localhost:8080"
TENANTS_DIR = Path(__file__).resolve().parent / "tenants"


def _parse_yaml_minimal(text: str) -> dict:
    """Parser YAML mínimo: só suporta chaves simples e dicts aninhados."""
    import re
    result: dict = {}
    stack: list[tuple[int, dict]] = [(-1, result)]

    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip().rstrip()

        # Pop stack to correct indent level
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        current = stack[-1][1]
        if not val or val.startswith("#"):
            # Nested dict
            new_dict: dict = {}
            current[key] = new_dict
            stack.append((indent, new_dict))
        else:
            # Scalar or inline dict
            if val.startswith("#"):
                val = ""
            val = val.split("#")[0].strip()
            # Type coercion
            if val.lower() in ("true", "yes"):
                current[key] = True
            elif val.lower() in ("false", "no"):
                current[key] = False
            else:
                try:
                    current[key] = int(val)
                except ValueError:
                    try:
                        current[key] = float(val)
                    except ValueError:
                        current[key] = val.strip('"\'')
    return result


def load_tenant_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if yaml:
        return yaml.safe_load(text)
    return _parse_yaml_minimal(text)


def push_overrides(tenant_id: str, overrides: dict) -> dict:
    """Envia overrides via PUT /v1/overrides com X-Aion-Tenant header."""
    payload = json.dumps(overrides).encode("utf-8")
    req = urllib.request.Request(
        f"{AION_URL}/v1/overrides",
        data=payload,
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "X-Aion-Tenant": tenant_id,
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def main():
    if not TENANTS_DIR.exists():
        print(f"  [tenant_init] Pasta tenants/ não encontrada: {TENANTS_DIR}")
        sys.exit(1)

    yamls = sorted(TENANTS_DIR.glob("*.yaml"))
    if not yamls:
        print("  [tenant_init] Nenhum arquivo .yaml encontrado em tenants/")
        return

    print("\n  Configurando tenants...\n")
    ok = 0
    for yaml_path in yamls:
        cfg = load_tenant_yaml(yaml_path)
        tenant_id = cfg.get("tenant_id", yaml_path.stem)

        # Extrai overrides aplicáveis
        overrides: dict = {}
        if "rate_limit" in cfg:
            overrides["rate_limit"] = cfg["rate_limit"]
        if "pii_policy" in cfg:
            overrides["pii_policy"] = cfg["pii_policy"]

        if not overrides:
            print(f"  [{tenant_id}] Sem overrides para aplicar.")
            continue

        try:
            result = push_overrides(tenant_id, overrides)
            keys = list(result.get("overrides", {}).keys())
            print(f"  [{tenant_id}] OK — overrides ativos: {keys}")
            ok += 1
        except urllib.error.URLError as e:
            print(f"  [{tenant_id}] ERRO — {e}")
        except Exception as e:
            print(f"  [{tenant_id}] ERRO inesperado — {e}")

    print(f"\n  {ok}/{len(yamls)} tenants configurados.\n")


if __name__ == "__main__":
    main()
