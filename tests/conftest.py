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
