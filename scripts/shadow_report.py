"""Shadow report — operador's go/no-go para ligar o enforce do acumulador de suspeita.

Consulta GET /v1/threats/{tenant} e resume os sinais `accumulated_pressure` ativos.
Durante o shadow (Fase 1 observe-only), o critério de aprovação é ZERO sinal sobre
conversa legítima. Para cada sinal, inspecione a sessão antes de aprovar.

    python scripts/shadow_report.py --base http://127.0.0.1:8095 --admin <key> --tenant <t> [--tenant <t2> ...]
"""
from __future__ import annotations

import argparse
import json

import httpx


def report(base: str, admin: str, tenants: list[str]) -> None:
    with httpx.Client(timeout=10.0) as c:
        for t in tenants:
            try:
                r = c.get(
                    f"{base}/v1/threats/{t}",
                    headers={"Authorization": f"Bearer {admin}", "X-Aion-Tenant": t},
                )
                data = r.json()
            except Exception as e:
                print(f"[{t}] ERRO: {type(e).__name__}: {e}")
                continue
            threats = data.get("threats", [])
            accum = [s for s in threats if s.get("pattern") == "accumulated_pressure"]
            print(f"\n=== tenant '{t}' — {len(threats)} sinais ({len(accum)} accumulated_pressure) ===")
            for s in accum:
                print(
                    f"  session={s.get('session_id')} conf={s.get('confidence')} "
                    f"action={s.get('recommended_action')} turns={s.get('turns_analyzed')}"
                )
            if not accum:
                print("  (nenhum accumulated_pressure — bom sinal de FP-zero, mas confirme volume de tráfego)")
            print("  ACAO: inspecione cada sessao acima. Sinal sobre conversa legitima = FP -> NAO ligar enforce.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8095")
    ap.add_argument("--admin", required=True)
    ap.add_argument("--tenant", action="append", required=True, dest="tenants")
    args = ap.parse_args()
    report(args.base, args.admin, args.tenants)
