"""KAIROS store factory — selects backend based on KAIROS_STORAGE_MODE.

Storage modes:
  sqlite   → POC/demo/dev (default, zero infra required)
  postgres → enterprise persistent store (customer's local Postgres)
  redis    → ephemeral only; data lost on restart — NOT for production
"""

from __future__ import annotations

from aion.kairos.settings import KairosSettings
from aion.kairos.store.base import KairosStore


def get_kairos_store(settings: KairosSettings) -> KairosStore:
    mode = settings.storage_mode
    if mode == "sqlite":
        from aion.kairos.store.sqlite_store import SQLiteKairosStore  # noqa: PLC0415
        return SQLiteKairosStore(settings.sqlite_path)
    if mode == "postgres":
        from aion.kairos.store.postgres_store import PostgresKairosStore  # noqa: PLC0415
        return PostgresKairosStore(settings.postgres_dsn)
    if mode == "redis":
        from aion.kairos.store.redis_store import RedisKairosStore  # noqa: PLC0415
        return RedisKairosStore()
    raise ValueError(
        f"Unknown KAIROS_STORAGE_MODE: {mode!r}. Valid values: sqlite | postgres | redis"
    )


__all__ = ["KairosStore", "get_kairos_store"]
