"""LLM Proxy — forwards requests to the configured LLM provider.

Supports batch and streaming (SSE) modes.
Handles multiple providers (OpenAI, Anthropic, Google) with format adapters.
Includes circuit breaker and retry with exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import AsyncIterator, Optional

import httpx

from aion.config import get_proxy_settings, get_settings
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
# Lock created at module load — safe in Python 3.10+ (no running event loop required)
_client_lock: asyncio.Lock = asyncio.Lock()

# ── Circuit breaker state (local + Redis-backed for cross-instance awareness) ──
_cb_failures: dict[str, int] = {}  # provider → consecutive failures
_cb_open_until: dict[str, float] = {}  # provider → timestamp when breaker closes
_CB_REDIS_PREFIX = "aion:cb:"
# CB threshold/recovery read from AionSettings (circuit_breaker_threshold / circuit_breaker_recovery_seconds)

# Redis for circuit breaker state (lazy init, separate from middleware Redis)
_cb_redis_client = None
_cb_redis_available = False
_cb_redis_lock: asyncio.Lock = asyncio.Lock()


async def _get_cb_redis():
    """Lazy Redis client for circuit breaker state sharing. Returns None if unavailable."""
    global _cb_redis_client, _cb_redis_available
    if _cb_redis_client is not None and _cb_redis_available:
        return _cb_redis_client
    redis_url = get_settings().redis_url
    if not redis_url:
        return None
    async with _cb_redis_lock:
        if _cb_redis_client is not None and _cb_redis_available:
            return _cb_redis_client
        try:
            import redis.asyncio as aioredis
            _cb_redis_client = aioredis.from_url(redis_url, decode_responses=True, socket_timeout=get_proxy_settings().cb_redis_socket_timeout)
            await _cb_redis_client.ping()
            _cb_redis_available = True
            return _cb_redis_client
        except Exception:
            _cb_redis_available = False
            _cb_redis_client = None
            return None


async def _get_client() -> httpx.AsyncClient:
    """Return shared httpx client. Creates it once under an asyncio lock."""
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            ps = get_proxy_settings()
            _client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=ps.http_connect_timeout,
                    read=ps.http_read_timeout,
                    write=ps.http_write_timeout,
                    pool=ps.http_pool_timeout,
                ),
                limits=httpx.Limits(
                    max_connections=ps.http_max_connections,
                    max_keepalive_connections=ps.http_max_keepalive_connections,
                ),
            )
    return _client


async def shutdown_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def _check_circuit_breaker(provider: str) -> bool:
    """Returns True if circuit is OPEN. Checks Redis for cross-instance state."""
    open_until = _cb_open_until.get(provider, 0)
    if open_until > 0:
        if time.time() < open_until:
            return True
        _cb_open_until[provider] = 0
        _cb_failures[provider] = 0

    try:
        r = await _get_cb_redis()
        if r:
            val = await r.get(f"{_CB_REDIS_PREFIX}{provider}:open_until")
            if val:
                open_until_redis = float(val)
                if time.time() < open_until_redis:
                    _cb_open_until[provider] = open_until_redis
                    return True
                await r.delete(f"{_CB_REDIS_PREFIX}{provider}:open_until")
    except Exception:
        pass

    return False


async def _record_success(provider: str) -> None:
    _cb_failures[provider] = 0
    _cb_open_until[provider] = 0
    try:
        r = await _get_cb_redis()
        if r:
            await r.delete(
                f"{_CB_REDIS_PREFIX}{provider}:open_until",
                f"{_CB_REDIS_PREFIX}{provider}:failures",
            )
    except Exception:
        pass


async def _record_failure(provider: str) -> None:
    s = get_settings()
    _cb_failures[provider] = _cb_failures.get(provider, 0) + 1
    if _cb_failures[provider] >= s.circuit_breaker_threshold:
        _cb_open_until[provider] = time.time() + s.circuit_breaker_recovery_seconds
        logger.warning(
            "Circuit breaker OPEN for provider '%s' — %d failures, recovery in %ds",
            provider, _cb_failures[provider], s.circuit_breaker_recovery_seconds,
        )
        try:
            r = await _get_cb_redis()
            if r:
                await r.setex(
                    f"{_CB_REDIS_PREFIX}{provider}:open_until",
                    int(s.circuit_breaker_recovery_seconds * 2),
                    str(_cb_open_until[provider]),
                )
        except Exception:
            logger.debug("CB Redis write failed — circuit breaker state is process-local", exc_info=True)


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
    key = os.environ.get(env_var, "")
    # Fallback: AION_DEFAULT_API_KEY covers custom providers without naming convention
    return key or os.environ.get("AION_DEFAULT_API_KEY", "")


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
# Max retries / delays read from ProxySettings (max_retries / retry_base_delay / retry_max_delay)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def forward_request(
    request: ChatCompletionRequest,
    context: PipelineContext,
    settings,
) -> ChatCompletionResponse:
    """Forward request to LLM with circuit breaker and retry."""
    s = settings or get_settings()

    provider = context.selected_provider or s.default_provider
    model = context.selected_model or s.default_model
    base_url = _resolve_base_url(context, s)
    api_key = _resolve_api_key(provider)

    # Circuit breaker check
    if await _check_circuit_breaker(provider):
        raise httpx.HTTPStatusError(
            "Circuit breaker open",
            request=httpx.Request("POST", ""),
            response=httpx.Response(503),
        )

    payload = _build_payload(request, model, False, provider)
    url = _get_chat_url(base_url, provider)
    headers = _build_headers(provider, api_key)
    client = await _get_client()

    ps = get_proxy_settings()
    last_resp: Optional[httpx.Response] = None
    for attempt in range(ps.max_retries):
        resp: Optional[httpx.Response] = None
        try:
            resp = await client.post(url, json=payload, headers=headers)
            last_resp = resp

            if resp.status_code in _RETRYABLE_STATUS and attempt < ps.max_retries - 1:
                delay = min(ps.retry_base_delay * (2 ** attempt), ps.retry_max_delay)
                logger.warning(
                    "Retryable error %d from %s, attempt %d/%d, waiting %.1fs",
                    resp.status_code, provider, attempt + 1, ps.max_retries, delay,
                )
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()
            await _record_success(provider)

            data = resp.json()
            if provider == "anthropic":
                data = _adapt_anthropic_response(data)

            return ChatCompletionResponse(**data)

        except httpx.HTTPStatusError:
            if resp is None or resp.status_code not in _RETRYABLE_STATUS:
                await _record_failure(provider)
                raise
            # retryable status on last attempt — fall through to post-loop handler
        except Exception:
            await _record_failure(provider)
            raise

    # All retries exhausted with retryable errors — surface the real upstream response
    await _record_failure(provider)
    if last_resp is None:
        raise RuntimeError("forward_request: all retries exhausted but no response was captured")
    last_resp.raise_for_status()
    # raise_for_status() always raises here (all _RETRYABLE_STATUS codes are >=400)
    raise RuntimeError("forward_request: unreachable — raise_for_status did not raise")



async def forward_request_stream(
    request: ChatCompletionRequest,
    context: PipelineContext,
    settings,
) -> AsyncIterator[str]:
    """Forward request to LLM and yield SSE chunks (with circuit breaker)."""
    s = settings or get_settings()

    provider = context.selected_provider or s.default_provider
    model = context.selected_model or s.default_model
    base_url = _resolve_base_url(context, s)
    api_key = _resolve_api_key(provider)

    if await _check_circuit_breaker(provider):
        yield 'data: {"error": "Circuit breaker open"}\n\n'
        yield "data: [DONE]\n\n"
        return

    payload = _build_payload(request, model, True, provider)
    url = _get_chat_url(base_url, provider)
    headers = _build_headers(provider, api_key)
    client = await _get_client()

    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            await _record_success(provider)
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
        await _record_failure(provider)
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
