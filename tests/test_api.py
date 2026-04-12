"""Tests for the FastAPI application (integration tests).

These tests mock the LLM provider to avoid real API calls.
"""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from aion.shared.schemas import (
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    UsageInfo,
)


@pytest.fixture
def mock_llm_response():
    """Mock a successful LLM response."""
    return ChatCompletionResponse(
        id="chatcmpl-test",
        model="gpt-4o-mini",
        choices=[ChatCompletionChoice(
            message=ChatMessage(role="assistant", content="Paris is the capital of France."),
        )],
        usage=UsageInfo(prompt_tokens=10, completion_tokens=8, total_tokens=18),
    )


@pytest.fixture
async def client():
    # Import app fresh and ensure pipeline is built
    from aion.main import app, lifespan
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Trigger lifespan startup
        yield c


@pytest.mark.asyncio
async def test_health(client):
    # Ensure pipeline is initialized
    import aion.main as main_mod
    from aion.pipeline import build_pipeline
    if main_mod._pipeline is None:
        main_mod._pipeline = build_pipeline()

    resp = await client.get("/health")
    assert resp.status_code in (200, 207)  # 200=normal, 207=degraded/safe
    data = resp.json()
    assert "version" in data
    assert "mode" in data


@pytest.mark.asyncio
async def test_stats_empty(client):
    resp = await client.get("/v1/stats")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_models(client):
    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert len(data["models"]) >= 1


@pytest.mark.asyncio
async def test_chat_completions_passthrough(client, mock_llm_response):
    """Test that a normal request passes through to the LLM (mocked)."""
    with patch("aion.main.forward_request", new_callable=AsyncMock) as mock_fwd:
        mock_fwd.return_value = mock_llm_response

        resp = await client.post("/v1/chat/completions", json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Paris is the capital of France."
        assert resp.headers.get("x-aion-decision") == "passthrough"
