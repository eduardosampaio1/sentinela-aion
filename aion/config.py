"""AION configuration via pydantic-settings."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FailMode(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class AionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server ---
    port: int = 8080
    fail_mode: FailMode = FailMode.OPEN
    log_level: str = "info"

    # --- Module toggles ---
    estixe_enabled: bool = True
    nomos_enabled: bool = False
    metis_enabled: bool = False

    # --- Default LLM (used when NOMOS is off) ---
    default_provider: str = "openai"
    default_model: str = "gpt-4o-mini"
    default_base_url: Optional[str] = None  # None = use provider default

    # --- Redis (optional) ---
    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")

    # --- ARGOS integration (optional) ---
    argos_telemetry_url: Optional[str] = Field(default=None, alias="ARGOS_TELEMETRY_URL")

    # --- Multi-tenancy ---
    tenant_header: str = "X-Aion-Tenant"
    default_tenant: str = "default"

    # --- Paths ---
    config_dir: Path = Path("config")

    # --- Circuit breaker ---
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_seconds: int = 30


class EstixeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ESTIXE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bypass_threshold: float = 0.85
    embedding_model: str = "all-MiniLM-L6-v2"
    max_tokens_per_request: int = 4096
    intents_path: Path = Path("aion/estixe/data/intents.yaml")
    cache_embeddings: bool = True


class NomosSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOMOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    models_config_path: Path = Path("config/models.yaml")
    fallback_enabled: bool = True
    cost_optimization: bool = True


class MetisSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="METIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    stream_mode: str = "passthrough"  # passthrough | buffer
    compression_enabled: bool = True
    max_history_turns: int = 10


# Singletons
_settings: Optional[AionSettings] = None
_estixe_settings: Optional[EstixeSettings] = None
_nomos_settings: Optional[NomosSettings] = None
_metis_settings: Optional[MetisSettings] = None


def get_settings() -> AionSettings:
    global _settings
    if _settings is None:
        _settings = AionSettings()
    return _settings


def get_estixe_settings() -> EstixeSettings:
    global _estixe_settings
    if _estixe_settings is None:
        _estixe_settings = EstixeSettings()
    return _estixe_settings


def get_nomos_settings() -> NomosSettings:
    global _nomos_settings
    if _nomos_settings is None:
        _nomos_settings = NomosSettings()
    return _nomos_settings


def get_metis_settings() -> MetisSettings:
    global _metis_settings
    if _metis_settings is None:
        _metis_settings = MetisSettings()
    return _metis_settings
