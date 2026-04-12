"""LLM Proxy — forwards requests to the configured LLM provider.

Supports batch and streaming (SSE) modes.
Handles multiple providers (OpenAI, Anthropic, Google) with format adapters.
Includes circuit breaker and retry with exponential backoff.
"""

from __future__ import annotations

import json
import logging
import os
import time
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

# ── Circuit breaker state ──
_cb_failures: dict[str, int] = {}  # provider → consecutive failures
_cb_open_until: dict[str, float] = {}  # provider → timestamp when breaker closes
_CB_THRESHOLD = 5
_CB_RECOVERY_SECONDS = 30


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


def _check_circuit_breaker(provider: str) -> bool:
    """Returns True if circuit is OPEN (should NOT call provider)."""
    open_until = _cb_open_until.get(provider, 0)
    if open_until > 0:
        if time.time() < open_until:
            return True  # circuit open
        else:
            # Recovery period passed — half-open, allow one attempt
            _cb_open_until[provider] = 0
            _cb_failures[provider] = 0
    return False


def _record_success(provider: str) -> None:
    _cb_failures[provider] = 0
    _cb_open_until[provider] = 0


def _record_failure(provider: str) -> None:
    _cb_failures[provider] = _cb_failures.get(provider, 0) + 1
    if _cb_failures[provider] >= _CB_THRESHOLD:
        _cb_open_until[provider] = time.time() + _CB_RECOVERY_SECONDS
        logger.warning(
            "Circuit breaker OPEN for provider '%s' — %d failures, recovery in %ds",
            provider, _cb_failures[provider], _CB_RECOVERY_SECONDS,
        )


def _resolve_base_url(context: PipelineContext, settings) -> str:
    if context.selected_base_url:
        return context.selected_base_url
    if settings.default_base_url:
        return settings.default_base_url
    provider = context.selected_provider or settings.default_provider
    return _PROVIDER_URLS.get(provider, _PROVIDER_URLS["openai"])


def _resolve_api_key(provider: str) -> str:
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
    }
    env_var = key_map.get(provider, f"{provider.upper()}_API_KEY")
    return os.environ.get(env_var, "")


def _build_headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _build_payload(request: ChatCompletionRequest, model: str, stream: bool, provider: str) -> dict:
    """Build provider-specific payload. Preserves extra fields for passthrough."""
    payload = request.model_dump(exclude_none=True)
    payload["model"] = model
    payload["stream"] = stream

    if provider == "anthropic":
        return _adapt_to_anthropic(payload)

    return payload


def _adapt_to_anthropic(payload: dict) -> dict:
    """Convert OpenAI-format payload to Anthropic Messages API format."""
    messages = payload.get("messages", [])

    # Extract system message
    system_text = ""
    non_system = []
    for msg in messages:
        if msg.get("role") == "system":
            system_text += (msg.get("content") or "") + "\n"
        else:
            non_system.append(msg)

    anthropic_payload = {
        "model": payload["model"],
        "messages": non_system,
        "max_tokens": payload.get("max_tokens", 4096),
    }

    if system_text.strip():
        anthropic_payload["system"] = system_text.strip()

    if payload.get("temperature") is not None:
        anthropic_payload["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        anthropic_payload["top_p"] = payload["top_p"]
    if payload.get("stream"):
        anthropic_payload["stream"] = True

    return anthropic_payload


def _adapt_anthropic_response(data: dict) -> dict:
    """Convert Anthropic response to OpenAI format."""
    content_blocks = data.get("content", [])
    text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")

    usage = data.get("usage", {})

    return {
        "id": data.get("id", ""),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.get("model", ""),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": data.get("stop_reason", "stop"),
        }],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }


def _get_chat_url(base_url: str, provider: str) -> str:
    """Get the chat completions URL for the provider."""
    if provider == "anthropic":
        return f"{base_url}/messages"
    return f"{base_url}/chat/completions"


# ── Retry with exponential backoff ──

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds
_RETRY_MAX_DELAY = 10.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def forward_request(
    request: ChatCompletionRequest,
    context: PipelineContext,
    settings,
) -> ChatCompletionResponse:
    """Forward request to LLM with circuit breaker and retry."""
    from aion.config import get_settings
    s = settings or get_settings()

    provider = context.selected_provider or s.default_provider
    model = context.selected_model or s.default_model
    base_url = _resolve_base_url(context, s)
    api_key = _resolve_api_key(provider)

    # Circuit breaker check
    if _check_circuit_breaker(provider):
        raise httpx.HTTPStatusError(
            "Circuit breaker open",
            request=httpx.Request("POST", ""),
            response=httpx.Response(503),
        )

    payload = _build_payload(request, model, False, provider)
    url = _get_chat_url(base_url, provider)
    headers = _build_headers(provider, api_key)
    client = _get_client()

    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
                import asyncio
                delay = min(_RETRY_BASE_DELAY * (2 ** attempt), _RETRY_MAX_DELAY)
                logger.warning(
                    "Retryable error %d from %s, attempt %d/%d, waiting %.1fs",
                    resp.status_code, provider, attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()
            _record_success(provider)

            data = resp.json()
            if provider == "anthropic":
                data = _adapt_anthropic_response(data)

            return ChatCompletionResponse(**data)

        except httpx.HTTPStatusError:
            last_error = resp
            if resp.status_code not in _RETRYABLE_STATUS:
                _record_failure(provider)
                raise
        except Exception as exc:
            _record_failure(provider)
            raise

    # All retries exhausted
    _record_failure(provider)
    if last_error:
        last_error.raise_for_status()
    raise httpx.HTTPStatusError("All retries exhausted", request=httpx.Request("POST", url), response=httpx.Response(502))


async def forward_request_stream(
    request: ChatCompletionRequest,
    context: PipelineContext,
    settings,
) -> AsyncIterator[str]:
    """Forward request to LLM and yield SSE chunks (with circuit breaker)."""
    from aion.config import get_settings
    s = settings or get_settings()

    provider = context.selected_provider or s.default_provider
    model = context.selected_model or s.default_model
    base_url = _resolve_base_url(context, s)
    api_key = _resolve_api_key(provider)

    if _check_circuit_breaker(provider):
        yield 'data: {"error": "Circuit breaker open"}\n\n'
        yield "data: [DONE]\n\n"
        return

    payload = _build_payload(request, model, True, provider)
    url = _get_chat_url(base_url, provider)
    headers = _build_headers(provider, api_key)
    client = _get_client()

    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            _record_success(provider)
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    chunk_data = line[6:]
                    if chunk_data.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                        break
                    yield f"data: {chunk_data}\n\n"
    except Exception:
        _record_failure(provider)
        raise


def build_bypass_stream(response: ChatCompletionResponse) -> AsyncIterator[str]:
    """Convert a bypass response into SSE stream format."""

    async def _stream():
        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""

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
