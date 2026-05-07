"""KAIROS settings — Policy Lifecycle Manager configuration."""

from __future__ import annotations

from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_STORAGE_MODES = {"sqlite", "postgres", "redis"}


class KairosSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KAIROS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = True

    # Storage backend.
    # sqlite  → source of truth for POC/demo/development (default — zero infra required)
    # postgres → source of truth for enterprise (customer's local Postgres)
    # redis   → ephemeral only; data lost on restart — NOT for production
    storage_mode: str = "sqlite"

    # Postgres DSN (used when storage_mode=postgres)
    postgres_dsn: Optional[str] = None

    # SQLite file path (used when storage_mode=sqlite)
    sqlite_path: str = ".kairos/kairos.db"

    # Shadow run completion thresholds
    shadow_min_observations: int = 500
    shadow_duration_hours: int = 168  # 7 days

    # Lifecycle sweep interval (seconds)
    sweep_interval_seconds: int = 300

    # Sanitized telemetry export (opt-in — Sentinela Cloud only)
    # Zero data leaves the client environment when telemetry_enabled=false.
    telemetry_enabled: bool = False
    telemetry_endpoint: Optional[str] = None
    telemetry_api_key: Optional[str] = None

    @field_validator("storage_mode")
    @classmethod
    def validate_storage_mode(cls, v: str) -> str:
        if v not in _VALID_STORAGE_MODES:
            raise ValueError(
                f"KAIROS_STORAGE_MODE must be one of {sorted(_VALID_STORAGE_MODES)}, got {v!r}"
            )
        return v


_settings: Optional[KairosSettings] = None


def get_kairos_settings() -> KairosSettings:
    global _settings
    if _settings is None:
        _settings = KairosSettings()
    return _settings


def reset_kairos_settings() -> None:
    """Reset settings singleton — for testing only."""
    global _settings
    _settings = None
