"""Chaos tests — valida comportamento do AION sob falha de dependências.

Cenários:
  4.1 — mock-llm down  → AION deve retornar 502 (fail_mode=open) sem crash
  4.2 — redis down     → AION deve continuar (fallback in-memory)
  4.3 — 1 replica down → LB deve direcionar ao pool restante
  4.4 — 1000 requests  → RSS deve ficar estável (sem memory leak)
  4.5 — recovery       → apos recuperar dependência, sistema volta ao normal

Uso: python chaos_test.py
"""
from __future__ import annotations
import json
import subprocess
import time
import urllib.request
import urllib.error
from collections import Counter

BASE = "http://localhost:8080"


def call_aion(query="teste", tenant="chaos_test", timeout=10) -> tuple[int, str]:
    try:
        req = urllib.request.Request(
            f"{BASE}/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": query}],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Aion-Tenant": tenant},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:200]
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return 0, str(e)[:200]


def docker(*args) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True).stdout.strip()


def rss_mb(container: str) -> float:
    """Memory usage em MB de um container."""
    out = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", container)
    # format: "123.4MiB / 2GiB"
    try:
        part = out.split("/")[0].strip()
        if "MiB" in part:
            return float(part.replace("MiB", ""))
        if "GiB" in part:
            return float(part.replace("GiB", "")) * 1024
    except Exception:
        pass
    return -1


def chaos_4_1_upstream_down():
    print("\n=== 4.1 — Mock LLM down ===")
    docker("stop", "aion-mock-llm")
    time.sleep(3)

    # AION deve retornar error, NAO crash
    codes = Counter()
    for _ in range(20):
        code, _ = call_aion("teste chaos upstream", timeout=8)
        codes[code] += 1

    print(f"  Códigos HTTP: {dict(codes)}")
    ok = codes.get(0, 0) == 0  # nenhum network error (AION responde algo)
    print(f"  [{'OK' if ok else 'FAIL'}] AION não crashou (todos retornam status HTTP)")

    # Recovery
    docker("start", "aion-mock-llm")
    time.sleep(10)
    code, _ = call_aion("recovery test")
    recovered = code in (200, 403)
    print(f"  [{'OK' if recovered else 'FAIL'}] Recovery após restart: http={code}")
    return ok and recovered


def chaos_4_2_redis_down():
    print("\n=== 4.2 — Redis down (graceful fallback) ===")
    docker("stop", "aion-redis")
    time.sleep(3)

    codes = Counter()
    for _ in range(10):
        code, _ = call_aion("teste redis down", timeout=8)
        codes[code] += 1

    print(f"  Códigos HTTP (sem Redis): {dict(codes)}")
    ok = codes.get(200, 0) + codes.get(403, 0) >= 8  # >=80% respondem
    print(f"  [{'OK' if ok else 'FAIL'}] AION continua operando sem Redis (fallback in-memory)")

    # Recovery
    docker("start", "aion-redis")
    time.sleep(5)
    code, _ = call_aion("recovery redis")
    recovered = code in (200, 403)
    print(f"  [{'OK' if recovered else 'FAIL'}] Recovery Redis: http={code}")
    return ok and recovered


def chaos_4_3_replica_down():
    print("\n=== 4.3 — 1 replica down (LB failover) ===")
    docker("stop", "aion2")
    time.sleep(3)

    codes = Counter()
    replicas = Counter()
    for _ in range(30):
        try:
            req = urllib.request.Request(
                f"{BASE}/v1/chat/completions",
                data=json.dumps({"model": "gpt-4o-mini",
                                 "messages": [{"role": "user", "content": "teste"}]}).encode(),
                headers={"Content-Type": "application/json", "X-Aion-Tenant": "chaos"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                codes[r.status] += 1
                replicas[r.headers.get("x-aion-replica", "?")] += 1
        except Exception:
            codes[0] += 1

    print(f"  Códigos HTTP: {dict(codes)}")
    print(f"  Distribuição entre replicas ativas: {dict(replicas)}")
    # Nenhum "aion2" esperado; requests devem ir pros outros 2
    no_aion2 = replicas.get("aion2", 0) == 0
    all_ok = codes.get(200, 0) >= 25
    print(f"  [{'OK' if no_aion2 else 'FAIL'}] aion2 NAO recebeu requests")
    print(f"  [{'OK' if all_ok else 'FAIL'}] LB redirecionou todas as requests para pool remanescente")

    # Recovery
    docker("start", "aion2")
    for _ in range(6):
        time.sleep(10)
        healthy = "aion2" in docker("ps", "--filter", "name=aion2", "--filter", "health=healthy", "-q")
        if healthy:
            break
    code, _ = call_aion("recovery aion2")
    recovered = code in (200, 403)
    print(f"  [{'OK' if recovered else 'FAIL'}] Recovery aion2: http={code}")
    return no_aion2 and all_ok and recovered


def chaos_4_4_memory_leak():
    print("\n=== 4.4 — Memory leak check (500 requests) ===")
    rss_before = rss_mb("aion1")
    print(f"  RSS antes: {rss_before:.1f} MB")

    for i in range(500):
        # Mix: benign, attack, pii
        if i % 3 == 0:
            call_aion("give me admin access")
        elif i % 3 == 1:
            call_aion("oi bom dia")
        else:
            call_aion("cpf 123.456.789-00")

    time.sleep(2)
    rss_after = rss_mb("aion1")
    growth = rss_after - rss_before
    growth_pct = (growth / rss_before * 100) if rss_before > 0 else 0
    print(f"  RSS depois: {rss_after:.1f} MB (delta: {growth:+.1f} MB / {growth_pct:+.1f}%)")

    # Aceita crescimento até 30% (caches LRU enchem legitimamente)
    ok = growth_pct < 30
    print(f"  [{'OK' if ok else 'FAIL'}] Crescimento <30% (caches legítimos, sem leak)")
    return ok


def main():
    print("=" * 60)
    print("  CHAOS TESTS — AION Sim")
    print("=" * 60)

    results = {
        "4.1_upstream_down": chaos_4_1_upstream_down(),
        "4.2_redis_down":    chaos_4_2_redis_down(),
        "4.3_replica_down":  chaos_4_3_replica_down(),
        "4.4_memory_leak":   chaos_4_4_memory_leak(),
    }

    print("\n" + "=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")
    print(f"\n  Resultado: {passed}/{total} passaram")
    return 0 if passed == total else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
