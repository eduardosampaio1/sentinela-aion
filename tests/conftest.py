"""Shared test fixtures."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set test environment before importing anything
os.environ.setdefault("AION_FAIL_MODE", "open")
os.environ.setdefault("AION_ESTIXE_ENABLED", "true")
os.environ.setdefault("AION_NOMOS_ENABLED", "false")
os.environ.setdefault("AION_METIS_ENABLED", "false")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Reset in-process global state between tests to prevent test order pollution.

    Resets: rate limiter, behavior store, module consecutive-failure counters,
    tenant overrides (in-memory only), and config singleton.
    Does NOT rebuild the pipeline — too slow and tests handle pipeline state locally.
    """
    yield
    # ── middleware state ─────────────────────────────────────────────────────
    import aion.middleware as mw
    mw._local_rate_limits.clear()
    mw._local_overrides.clear()
    mw._redis_client = None
    mw._redis_available = False

    # ── metis behavior store ─────────────────────────────────────────────────
    try:
        from aion.metis.behavior import _behavior_store
        _behavior_store.clear()
    except Exception:
        pass

    # ── pipeline: reset module failure counters and safe mode ─────────────────
    import aion.main as main_mod
    if main_mod._pipeline is not None:
        main_mod._pipeline.deactivate_safe_mode()
        for status in main_mod._pipeline._module_status.values():
            status.consecutive_failures = 0
            status.healthy = True

    # ── config singleton ─────────────────────────────────────────────────────
    import aion.config
    aion.config._settings = None


@pytest.fixture
def chat_request_data():
    """Basic chat completion request payload."""
    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "What is the capital of France?"}
        ],
    }


@pytest.fixture
def greeting_request_data():
    """Chat request with a greeting."""
    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "oi"}
        ],
    }


@pytest.fixture
def stream_request_data():
    """Chat request with streaming enabled."""
    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Tell me a joke"}
        ],
        "stream": True,
    }
