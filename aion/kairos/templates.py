"""KAIROS template loader — reads YAML catalogs into PolicyTemplate objects.

Templates ship inside the aion.kairos.data package (importlib.resources) so they
are included in wheel installs without extra packaging configuration.

The loader caches parsed templates in memory. Hot-reload is not supported —
call reload_templates() or restart AION to pick up template changes.
"""

from __future__ import annotations

import importlib.resources as pkg_resources
import logging
from pathlib import Path
from typing import Optional

import yaml

from aion.kairos.models import PolicyTemplate

logger = logging.getLogger("aion.kairos.templates")

_CACHE: Optional[list[PolicyTemplate]] = None


def _default_catalog() -> Path:
    ref = pkg_resources.files("aion.kairos.data").joinpath("financial_templates.yaml")
    return Path(str(ref))


def load_templates(catalog_path: Optional[Path] = None) -> list[PolicyTemplate]:
    """Load all PolicyTemplate objects from the YAML catalog (cached)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    path = catalog_path or _default_catalog()
    if not path.exists():
        logger.warning("KAIROS template catalog not found: %s", path)
        return []  # do not cache — allow retry after file appears

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception:
        logger.warning("KAIROS: failed to parse template catalog %s", path, exc_info=True)
        return []  # do not cache — allow retry after corrupt file is replaced

    templates = []
    for item in (raw or []):
        try:
            templates.append(PolicyTemplate(
                id=item["id"],
                vertical=item.get("vertical", ""),
                type=item["type"],
                title=item["title"],
                description=item.get("description", ""),
                risk_level=item.get("risk_level", "low"),
                trigger=item.get("trigger", {}),
                action=item.get("action", {}),
                fallback=item.get("fallback", {}),
                exclusions=item.get("exclusions", []),
                default_thresholds=item.get("default_thresholds", []),
                default_success_criteria=item.get("default_success_criteria", []),
            ))
        except Exception:
            logger.warning("KAIROS: skipped malformed template %r", item.get("id"), exc_info=True)

    logger.info("KAIROS: loaded %d templates from %s", len(templates), path)
    _CACHE = templates
    return _CACHE


def get_template(template_id: str) -> Optional[PolicyTemplate]:
    """Return a single template by id, or None if not found."""
    return next((t for t in load_templates() if t.id == template_id), None)


def reload_templates() -> list[PolicyTemplate]:
    """Force reload from disk (clears cache)."""
    global _CACHE
    _CACHE = None
    return load_templates()
