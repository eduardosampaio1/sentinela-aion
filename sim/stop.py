"""Para todos os processos do ambiente simulado.

Uso:
    python stop.py
"""
import subprocess
import sys

PORTS = [8001, 8080, 3000, 3001]

def kill_port(port: int):
    result = subprocess.run(
        f'netstat -ano | findstr ":{port} "',
        shell=True, capture_output=True, text=True
    )
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if parts and "LISTENING" in line:
            pids.add(parts[-1])
    for pid in pids:
        try:
            subprocess.run(f"taskkill /PID {pid} /F", shell=True,
                           capture_output=True)
            print(f"  Parado PID {pid} (porta {port})")
        except Exception as e:
            print(f"  Erro ao parar PID {pid}: {e}")

print("\n  Parando ambiente simulado...\n")
for port in PORTS:
    kill_port(port)
print("\n  Pronto.\n")
