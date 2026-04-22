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

    # --- Environment (contract meta) ---
    environment: str = "prod"  # prod | staging | dev — validated by contract

    # --- Service registry (CALL_SERVICE) ---
    service_registry_path: Path = _PROJECT_DIR / "config" / "services.yaml"


class EstixeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ESTIXE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bypass_threshold: float = 0.85
    block_min_threshold: float = 0.82    # min confidence for action=block intents (prevents relaxation)
    risk_check_enabled: bool = True       # enable RiskClassifier (S3 structural risk layer)
    risk_check_threshold: float = 0.78   # default threshold for risk categories (overridden per-category in YAML)
    # Output guard usa threshold = risk_threshold + output_threshold_boost para reduzir
    # falsos positivos em respostas do LLM que mencionam termos sensiveis em contexto
    # benigno (ex: "fraude" em resposta sobre como reportar uma fraude). Input permanece
    # no threshold original (rigoroso) — output eh mais tolerante por design.
    output_threshold_boost: float = 0.06
    embedding_model: str = "all-MiniLM-L6-v2"
    max_tokens_per_request: int = 4096
    intents_path: Path = _PACKAGE_DIR / "estixe" / "data" / "intents.yaml"
    cache_embeddings: bool = True
    # ── Velocity detection (probing / brute-force attack mitigation) ──
    # When a tenant accumulates velocity_block_threshold blocks within
    # velocity_window_seconds, all risk thresholds are tightened by velocity_tighten_delta.
    # NOTE: state is process-local (non-distributed). For multi-process deployments,
    # delegate velocity tracking to NEMOS (which has tenant-scoped Redis state).
    velocity_enabled: bool = True
    velocity_block_threshold: int = 5      # blocks in window to trigger tightening
    velocity_window_seconds: int = 60      # rolling window size in seconds
    velocity_tighten_delta: float = 0.05   # how much to lower thresholds when triggered

    # ── Suggestions (auto-discovery) ──
    suggestions_enabled: bool = False  # opt-in: ESTIXE_SUGGESTIONS_ENABLED=true
    suggestions_min_cluster_size: int = 3
    suggestions_similarity_threshold: float = 0.85
    suggestions_sampling_rate: float = 1.0  # 1.0 = sample every passthrough

    # ── Shadow mode calibration / auto-promotion ──
    # Volume + time gates
    shadow_promote_min_requests: int = 1000
    shadow_promote_min_days: int = 7
    # Stability gate: max acceptable confidence std-dev before promotion.
    # Prevents promoting a noisy category (high variance = signal not yet stable).
    shadow_promote_min_stability: float = 0.05
    # Drift control: max threshold delta allowed per promotion step.
    # Prevents a single promotion from making a large jump (e.g. 0.74 → 0.85).
    shadow_promote_max_threshold_delta: float = 0.10
    # Cooldown: min days between two successive promotions of the same category.
    # Absorbs false signals from sudden traffic spikes.
    shadow_promote_cooldown_days: float = 3.0


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


class CacheSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AION_CACHE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = False  # opt-in: AION_CACHE_ENABLED=true
    similarity_threshold: float = 0.92  # high threshold — avoid false hits
    default_ttl_seconds: int = 21600  # 6 hours
    max_entries_per_tenant: int = 5000
    # TTL overrides by intent type (ESTIXE-classified)
    ttl_factual: int = 86400       # 24h — stable answers
    ttl_creative: int = 3600       # 1h — diverse answers expected
    ttl_code: int = 7200           # 2h — moderate variability
    # Invalidation
    followup_threshold: int = 2    # invalidate after N followups on same cached answer


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
    rewrite_level: str = "off"  # off | light | moderate


# Singletons
_settings: Optional[AionSettings] = None
_estixe_settings: Optional[EstixeSettings] = None
_nomos_settings: Optional[NomosSettings] = None
_metis_settings: Optional[MetisSettings] = None
_cache_settings: Optional[CacheSettings] = None


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


def get_cache_settings() -> CacheSettings:
    global _cache_settings
    if _cache_settings is None:
        _cache_settings = CacheSettings()
    return _cache_settings
