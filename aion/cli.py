"""AION CLI — entry point.

Ativa uvloop quando disponivel (2x throughput em I/O-bound workloads).
Suporta AION_WORKERS env var para multi-worker (produção).

Modo single-worker (default, dev): AION_WORKERS=1
  - Estado in-memory (DecisionCache, velocity local, classify cache) funciona.
  - Sufficient pra laptop + ~500 decisions/s.

Modo multi-worker (prod): AION_WORKERS=N (ex: 4 ou num CPU cores)
  - Cada worker e processo separado com estado in-memory próprio.
  - Throughput escala quase-linear com N workers.
  - Cache é duplicado por worker (warm-up custa N× mais memoria).
  - Para cache global cross-worker, use Redis-backed DecisionCache (v2).
"""

import os
import uvicorn
from aion.config import get_settings


def main():
    settings = get_settings()

    try:
        import uvloop  # noqa: F401
        loop = "uvloop"
    except ImportError:
        loop = "asyncio"

    workers = int(os.environ.get("AION_WORKERS", "1"))
    # $PORT is set by Render/Heroku/Railway — takes precedence over AION_PORT default
    port = int(os.environ.get("PORT", settings.port))

    uvicorn.run(
        "aion.main:app",
        host="0.0.0.0",
        port=port,
        log_level=settings.log_level,
        loop=loop,
        http="httptools",
        workers=workers if workers > 1 else None,  # None = single-process (habilita reload/debug)
    )


if __name__ == "__main__":
    main()
