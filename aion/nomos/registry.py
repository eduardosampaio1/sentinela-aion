"""Model registry — manages available LLM providers and their metadata."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from aion.config import NomosSettings

logger = logging.getLogger("aion.nomos.registry")


@dataclass
class ModelConfig:
    """Configuration for a single LLM model."""
    name: str
    provider: str
    api_key_env: str = ""
    base_url: Optional[str] = None
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    latency_p50_ms: int = 500
    capabilities: list[str] = field(default_factory=list)
    complexity_range: tuple[float, float] = (0, 100)
    enabled: bool = True

    @property
    def has_api_key(self) -> bool:
        """Check if the API key is available in environment."""
        if not self.api_key_env:
            return False
        return bool(os.environ.get(self.api_key_env))

    @property
    def estimated_cost_per_request(self) -> float:
        """Rough cost estimate for an average request (~500 input + 200 output tokens)."""
        return (500 * self.cost_per_1k_input + 200 * self.cost_per_1k_output) / 1000


class ModelRegistry:
    """Manages the available model pool."""

    def __init__(self, settings: NomosSettings) -> None:
        self._settings = settings
        self._models: list[ModelConfig] = []

    async def load(self, config_path: Optional[Path] = None) -> None:
        """Load model configs from YAML."""
        path = config_path or self._settings.models_config_path
        if not path.exists():
            logger.warning("Models config not found at %s", path)
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._models = []
        for model_data in data.get("models", []):
            complexity_range = model_data.get("complexity_range", [0, 100])
            model = ModelConfig(
                name=model_data["name"],
                provider=model_data.get("provider", "openai"),
                api_key_env=model_data.get("api_key_env", ""),
                base_url=model_data.get("base_url"),
                cost_per_1k_input=model_data.get("cost_per_1k_input", 0),
                cost_per_1k_output=model_data.get("cost_per_1k_output", 0),
                max_tokens=model_data.get("max_tokens", 4096),
                latency_p50_ms=model_data.get("latency_p50_ms", 500),
                capabilities=model_data.get("capabilities", []),
                complexity_range=tuple(complexity_range),
                enabled=model_data.get("enabled", True),
            )
            self._models.append(model)

        logger.info("Loaded %d models from registry", len(self._models))

    def get_available_models(self) -> list[ModelConfig]:
        """Get models that are enabled and have valid API keys."""
        return [m for m in self._models if m.enabled and m.has_api_key]

    def get_models_for_complexity(self, score: float) -> list[ModelConfig]:
        """Get models whose complexity range covers the given score."""
        available = self.get_available_models()
        matching = [
            m for m in available
            if m.complexity_range[0] <= score <= m.complexity_range[1]
        ]
        return matching

    def get_cheapest(self, models: Optional[list[ModelConfig]] = None) -> Optional[ModelConfig]:
        """Get the cheapest model from the list."""
        pool = models or self.get_available_models()
        if not pool:
            return None
        return min(pool, key=lambda m: m.estimated_cost_per_request)

    def get_fastest(self, models: Optional[list[ModelConfig]] = None) -> Optional[ModelConfig]:
        """Get the fastest model from the list."""
        pool = models or self.get_available_models()
        if not pool:
            return None
        return min(pool, key=lambda m: m.latency_p50_ms)

    def get_by_name(self, name: str) -> Optional[ModelConfig]:
        """Get a specific model by name."""
        for m in self._models:
            if m.name == name:
                return m
        return None

    @property
    def model_count(self) -> int:
        return len(self._models)

    async def reload(self) -> None:
        await self.load()
