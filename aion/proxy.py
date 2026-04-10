"""LLM Proxy — forwards requests to the configured LLM provider.

Supports both batch and streaming (SSE) modes.
Handles multiple providers (OpenAI, Anthropic, Google).
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

import httpx

from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionStreamChunk,
    PipelineContext,
)

logger = logging.getLogger("aion.proxy")

# Provider base URLs
_PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
}

# Shared httpx client for connection pooling
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _client


async def shutdown_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _resolve_base_url(context: PipelineContext, settings) -> str:
    """Resolve the base URL for the LLM provider."""
    if context.selected_base_url:
        return context.selected_base_url
    if settings.default_base_url:
        return settings.default_base_url

    provider = context.selected_provider or settings.default_provider
    return _PROVIDER_URLS.get(provider, _PROVIDER_URLS["openai"])


def _resolve_api_key(provider: str) -> str:
    """Resolve API key from environment for the given provider."""
    import os

    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
    }
    env_var = key_map.get(provider, f"{provider.upper()}_API_KEY")
    key = os.environ.get(env_var, "")
    if not key:
        logger.warning("No API key found for provider '%s' (env: %s)", provider, env_var)
    return key


def _build_headers(provider: str, api_key: str) -> dict[str, str]:
    """Build provider-specific headers."""
    headers = {"Content-Type": "application/json"}

    if provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    return headers


async def forward_request(
    request: ChatCompletionRequest,
    context: PipelineContext,
    settings,
) -> ChatCompletionResponse:
    """Forward request to LLM and return complete response (non-streaming)."""
    from aion.config import get_settings
    s = settings or get_settings()

    provider = context.selected_provider or s.default_provider
    model = context.selected_model or s.default_model
    base_url = _resolve_base_url(context, s)
    api_key = _resolve_api_key(provider)

    # Override model in request
    payload = request.model_dump(exclude_none=True, exclude={"extra"})
    payload["model"] = model
    payload["stream"] = False

    url = f"{base_url}/chat/completions"
    headers = _build_headers(provider, api_key)

    client = _get_client()
    resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    data = resp.json()
    return ChatCompletionResponse(**data)


async def forward_request_stream(
    request: ChatCompletionRequest,
    context: PipelineContext,
    settings,
) -> AsyncIterator[str]:
    """Forward request to LLM and yield SSE chunks."""
    from aion.config import get_settings
    s = settings or get_settings()

    provider = context.selected_provider or s.default_provider
    model = context.selected_model or s.default_model
    base_url = _resolve_base_url(context, s)
    api_key = _resolve_api_key(provider)

    payload = request.model_dump(exclude_none=True, exclude={"extra"})
    payload["model"] = model
    payload["stream"] = True

    url = f"{base_url}/chat/completions"
    headers = _build_headers(provider, api_key)

    client = _get_client()

    async with client.stream("POST", url, json=payload, headers=headers) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line:
                continue
            if line.startswith("data: "):
                chunk_data = line[6:]
                if chunk_data.strip() == "[DONE]":
                    yield "data: [DONE]\n\n"
                    break
                yield f"data: {chunk_data}\n\n"


def build_bypass_stream(response: ChatCompletionResponse) -> AsyncIterator[str]:
    """Convert a bypass response into SSE stream format."""

    async def _stream():
        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""

        # Send a single chunk with full content
        chunk = ChatCompletionStreamChunk(
            id=response.id,
            model=response.model,
            choices=[{
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None,
            }],
        )
        yield f"data: {json.dumps(chunk.model_dump())}\n\n"

        # Send finish chunk
        finish_chunk = ChatCompletionStreamChunk(
            id=response.id,
            model=response.model,
            choices=[{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
        )
        yield f"data: {json.dumps(finish_chunk.model_dump())}\n\n"
        yield "data: [DONE]\n\n"

    return _stream()
