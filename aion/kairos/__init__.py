"""KAIROS — Policy Lifecycle Manager.

Async governance module packaged with AION.
Operates completely outside the synchronous hot path.

Usage:
    from aion.kairos import get_kairos
    kairos = get_kairos()
    await kairos.store.save_candidate(candidate)
"""

from __future__ import annotations

import logging
from typing import Optional

from aion.kairos.settings import KairosSettings, get_kairos_settings
from aion.kairos.store import KairosStore, get_kairos_store
from aion.kairos.templates import load_templates

logger = logging.getLogger("aion.kairos")


class KairosModule:
    """Facade for KAIROS subsystems. Obtain via get_kairos()."""

    def __init__(self, settings: KairosSettings) -> None:
        self.settings = settings
        self._store: Optional[KairosStore] = None
        self._lifecycle_manager = None

    @property
    def store(self) -> KairosStore:
        if self._store is None:
            self._store = get_kairos_store(self.settings)
            logger.info(
                "KAIROS store initialised (mode=%s)",
                self.settings.storage_mode,
            )
        return self._store

    @property
    def lifecycle_manager(self) -> "KairosLifecycleManager":
        if self._lifecycle_manager is None:
            from aion.kairos.lifecycle import KairosLifecycleManager
            self._lifecycle_manager = KairosLifecycleManager(self.store, self.settings)
        return self._lifecycle_manager

    def preload_templates(self) -> int:
        """Warm template cache. Returns count of loaded templates."""
        templates = load_templates()
        return len(templates)


_instance: Optional[KairosModule] = None


def get_kairos() -> KairosModule:
    """Return the process-wide KairosModule singleton."""
    global _instance
    if _instance is None:
        settings = get_kairos_settings()
        if not settings.enabled:
            raise RuntimeError("KAIROS is disabled (KAIROS_ENABLED=false)")
        _instance = KairosModule(settings)
    return _instance


def reset_kairos() -> None:
    """Reset singleton — for testing only."""
    global _instance
    _instance = None


__all__ = ["KairosModule", "get_kairos", "reset_kairos"]
