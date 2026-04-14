"""AION configuration via pydantic-settings."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve paths relative to the aion package directory, not cwd
_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _PACKAGE_DIR.parent


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
    safe_mode: bool = False  # Kill switch: bypass all modules, pure passthrough

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

    # --- Auth ---
    admin_key: str = ""  # Comma-separated keys for rotation: "key1,key2"

    # --- Multi-tenancy ---
    tenant_header: str = "X-Aion-Tenant"
    default_tenant: str = "default"

    # --- Paths (resolved relative to project root) ---
    config_dir: Path = _PROJECT_DIR / "config"

    # --- Circuit breaker ---
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_seconds: int = 30

    # --- Security (POC/enterprise) ---
    cors_origins: str = ""  # Comma-separated origins, e.g. "http://localhost:3000,https://console.aion.io"
    require_chat_auth: bool = False  # Require API key for /v1/chat/completions
    require_tenant: bool = False  # Require explicit X-Aion-Tenant header (no fallback to "default")
    chat_rate_limit: int = 100  # Requests/min per tenant+IP for chat endpoint
    admin_rate_limit: int = 10  # Requests/min per tenant+IP for admin endpoints

    # --- Data retention ---
    telemetry_retention_hours: int = 168  # 7 days default


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
    intents_path: Path = _PACKAGE_DIR / "estixe" / "data" / "intents.yaml"
    cache_embeddings: bool = True


class ScoringWeights(BaseSettings):
    """Weights for NOMOS multi-factor model scoring. Lower total = better model."""
    model_config = SettingsConfigDict(
        env_prefix="NOMOS_WEIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cost: float = 10000.0
    fit: float = 0.5
    latency: float = 1.0
    risk_penalty: float = 50.0       # penalty when PII detected + low risk_tier model
    capability_miss: float = 20.0    # penalty per missing required capability
    learned: float = 1.0            # weight for NEMOS-learned performance factor


class NomosSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOMOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    models_config_path: Path = _PROJECT_DIR / "config" / "models.yaml"
    fallback_enabled: bool = True
    cost_optimization: bool = True
    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)


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
