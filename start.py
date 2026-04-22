"""AION Sim — Orquestrador principal.

Sobe tudo com um único comando:
    python start.py

Processos gerenciados:
    [1] mock_llm/server.py   → porta 8001  (mock LLM OpenAI-compatible)
    [2] AION                 → porta 8080  (pipeline ESTIXE+NOMOS+METIS)
    [3] console/server.py    → porta 3000  (interface web)

CTRL+C para parar tudo.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

# Garante stdout UTF-8 no Windows (evita UnicodeEncodeError com box-drawing chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import time
import urllib.request
from pathlib import Path

# ── Caminhos ──────────────────────────────────────────────────────────────
SIM_DIR  = Path(__file__).resolve().parent
ENV_FILE = SIM_DIR / ".env.sim"

# ── Carrega .env.sim ───────────────────────────────────────────────────────
def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env

cfg = load_env(ENV_FILE)

# Aplica no processo atual (sobrescreve qualquer valor anterior).
# IMPORTANTE: sobrescrever garantidamente apaga chaves reais do shell do desenvolvedor
# que poderiam vazar requests para OpenAI/Anthropic quando o .env.sim manda para mock.
for k, v in cfg.items():
    os.environ[k] = v

# ── Sim guardrail: nao deixa chave real vazar em sim ──
# Se o sim roteia para mock (AION_DEFAULT_BASE_URL aponta pra localhost) mas o shell
# tinha uma chave real, forca a chave do .env.sim (fake) a prevalecer.
_base = cfg.get("AION_DEFAULT_BASE_URL", "")
if _base.startswith("http://localhost") or _base.startswith("http://127."):
    for key_var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        sim_val = cfg.get(key_var, "")
        cur_val = os.environ.get(key_var, "")
        # "sim-" ou "fake" ou "not-real" = marcador no .env.sim
        is_sim = any(m in sim_val.lower() for m in ("sim", "fake", "demo", "not-real"))
        looks_real = cur_val.startswith(("sk-proj-", "sk-ant-api03-")) or (
            cur_val.startswith("sk-") and not any(m in cur_val.lower() for m in ("sim", "fake", "demo"))
        )
        if is_sim and looks_real and cur_val != sim_val:
            print(f"  AVISO: {key_var} real detectada no shell — forcando valor fake do .env.sim")
            os.environ[key_var] = sim_val

# NOMOS_MODELS_CONFIG_PATH como caminho absoluto (independe do CWD)
os.environ["NOMOS_MODELS_CONFIG_PATH"] = str(SIM_DIR / "config" / "models.sim.yaml")

AION_PATH    = Path(cfg.get("AION_PATH", r"D:\projetos\aion"))
CONSOLE_PATH = SIM_DIR / "aion-console"     # Next.js dashboard local do sentinela-aion
PYTHON       = sys.executable

# Detecta npm (Next.js)
import shutil as _shutil
NPM = _shutil.which("npm") or "npm"
PROCS: list[subprocess.Popen] = []


# ── Banner ─────────────────────────────────────────────────────────────────
def banner():
    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║        AION Sim  —  Ambiente Simulado        ║")
    print("  ╠══════════════════════════════════════════════╣")
    print(f"  ║  AION path  : {str(AION_PATH):<30} ║")
    print(f"  ║  Mock LLM   : http://localhost:8001         ║")
    print(f"  ║  AION API   : http://localhost:8080         ║")
    print(f"  ║  Console    : http://localhost:3000         ║")
    print("  ╠══════════════════════════════════════════════╣")
    print("  ║  CTRL+C para parar tudo                      ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()


# ── Health check ───────────────────────────────────────────────────────────
def wait_for(url: str, label: str, timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    sys.stdout.write(f"  Aguardando {label}...")
    sys.stdout.flush()
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            print(" OK")
            return True
        except Exception:
            time.sleep(2)
            sys.stdout.write(".")
            sys.stdout.flush()
    print(" TIMEOUT")
    return False


# ── Inicia processo ────────────────────────────────────────────────────────
def start_proc(args: list[str], cwd: Path | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    p = subprocess.Popen(args, cwd=str(cwd or SIM_DIR), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(p)
    return p


# ── Shutdown ───────────────────────────────────────────────────────────────
def shutdown(sig=None, frame=None):
    print("\n\n  Parando todos os processos...")
    for p in reversed(PROCS):
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    print("  Ambiente encerrado. Até logo!\n")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# ── Port collision detector ──
def _port_in_use(port: int) -> bool:
    """True se alguma coisa esta escutando na porta."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _check_port_collisions() -> None:
    """Aborta se alguma porta ja esta ocupada — evita duplicate-instance (AION silencioso).

    Sintoma do bug que isso previne: dois processos escutando em 0.0.0.0 e 127.0.0.1,
    um servindo mock_llm, outro vazando para OpenAI real.
    """
    ports = {8001: "Mock LLM", 8080: "AION API", 3000: "Chat Console", 3001: "AION Console"}
    busy = [(p, name) for p, name in ports.items() if _port_in_use(p)]
    if busy:
        print("\n  ERRO: porta(s) ja em uso — provavelmente instancia anterior nao foi encerrada.")
        for p, name in busy:
            print(f"    - {p} ({name})")
        print("\n  Resolva com:")
        print("    python stop.py")
        print("  ou manualmente:")
        print(r"    taskkill /F /IM python.exe /IM node.exe")
        sys.exit(1)


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    # Valida AION path
    if not AION_PATH.exists():
        print(f"\n  ERRO: AION não encontrado em {AION_PATH}")
        print(f"  Edite AION_PATH em {ENV_FILE}\n")
        sys.exit(1)

    _check_port_collisions()

    banner()
    print("  Iniciando serviços...\n")

    # [1] Mock LLM
    start_proc([PYTHON, str(SIM_DIR / "mock_llm" / "server.py")])
    if not wait_for("http://localhost:8001/health", "Mock LLM (8001)", timeout=15):
        shutdown()

    # [2] AION
    print("  Nota: primeira execução baixa modelo de embeddings (~150 MB via HuggingFace).")
    print("        Os pontos abaixo podem demorar até 3 min na primeira vez.\n")
    start_proc([PYTHON, "-m", "aion.cli"], cwd=AION_PATH)
    if not wait_for("http://localhost:8080/ready", "AION (8080)", timeout=180):
        shutdown()

    # [2.1] Configura tenants via API de overrides
    print("  Configurando tenants (nubank, inter, demo)...")
    try:
        import subprocess as _sp
        _sp.run([PYTHON, str(SIM_DIR / "tenant_init.py")], timeout=15)
    except Exception as e:
        print(f"  AVISO: tenant_init falhou — {e}")

    # [3] Console web (chat + trace panel)
    start_proc([PYTHON, str(SIM_DIR / "console" / "server.py")])
    if not wait_for("http://localhost:3000/index.html", "Console (3000)", timeout=10):
        shutdown()

    # [4] AION Console (Next.js — painel de controle com dados reais)
    if CONSOLE_PATH.exists():
        if not (CONSOLE_PATH / "node_modules").exists():
            print("  Instalando dependências do AION Console (primeira vez)...")
            result = subprocess.run(
                [NPM, "install"], cwd=str(CONSOLE_PATH),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                print("  AVISO: npm install falhou — pulando AION Console.")
                CONSOLE_PATH = None  # type: ignore[assignment]
        if CONSOLE_PATH is not None:
            start_proc([NPM, "run", "dev", "--", "--port", "3001"], cwd=CONSOLE_PATH)
            if not wait_for("http://localhost:3001", "AION Console (3001)", timeout=60):
                print("  AVISO: AION Console não subiu — continuando sem ele.")
    else:
        print("  AVISO: pasta aion-console não encontrada — pulando porta 3001.")

    print()
    print("  ✓ Ambiente simulado pronto!")
    print()
    print("  → Chat + trace:  http://localhost:3000")
    print("  → AION Console:  http://localhost:3001")
    print()

    # Mantém o processo vivo até CTRL+C
    try:
        while True:
            # Verifica se algum processo filho morreu inesperadamente
            for p in PROCS:
                if p.poll() is not None:
                    print(f"\n  AVISO: processo {p.args[0]} encerrou inesperadamente.")
            time.sleep(5)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
