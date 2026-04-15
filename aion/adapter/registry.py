"""Service registry — loads config/services.yaml for CALL_SERVICE action."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from aion.config import AionSettings, get_settings

logger = logging.getLogger("aion.adapter.registry")


@dataclass
class ServiceConfig:
    name: str
    endpoint: str
    auth_env: Optional[str] = None
    timeout_seconds: float = 5.0
    method: str = "POST"
    response_adapter: Optional[str] = None  # function name in aion/adapter/service_adapters.py
    capabilities: list[str] = field(default_factory=list)


class ServiceRegistry:
    """Loads and exposes service definitions from YAML."""

    def __init__(self, settings: Optional[AionSettings] = None) -> None:
        self._settings = settings or get_settings()
        self._services: dict[str, ServiceConfig] = {}

    async def load(self, config_path: Optional[Path] = None) -> None:
        path = config_path or getattr(self._settings, "service_registry_path", None)
        if not path or not Path(path).exists():
            logger.info("Service registry config not found — CALL_SERVICE will be unavailable")
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        for svc_data in data.get("services", []) or []:
            svc = ServiceConfig(
                name=svc_data["name"],
                endpoint=svc_data["endpoint"],
                auth_env=svc_data.get("auth_env"),
                timeout_seconds=svc_data.get("timeout_seconds", 5.0),
                method=svc_data.get("method", "POST"),
                response_adapter=svc_data.get("response_adapter"),
                capabilities=svc_data.get("capabilities", []),
            )
            self._services[svc.name] = svc

        logger.info("Loaded %d services from registry", len(self._services))

    def get(self, name: str) -> Optional[ServiceConfig]:
        return self._services.get(name)

    def list(self) -> list[ServiceConfig]:
        return list(self._services.values())
