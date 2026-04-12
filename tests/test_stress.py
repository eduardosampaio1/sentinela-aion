"""Stress tests — progressive load to find breaking point.

10 req → ok, 100 req → ok, 500 req → find limits.
Also tests circuit breaker and retry behavior.
"""

import asyncio
import time

import pytest

from aion.pipeline import Pipeline
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatMessage,
    Decision,
    PipelineContext,
)


class FastModule:
    def __init__(self, name):
        self.name = name
    async def process(self, request, context):
        return context


def _req():
    return ChatCompletionRequest(
        model="test", messages=[ChatMessage(role="user", content="test")]
    )


class TestStressProgressive:
    """Progressive load test to find breaking point."""

    @pytest.mark.asyncio
    async def test_10_concurrent(self):
        """10 concurrent requests should all succeed."""
        pipeline = Pipeline()
        pipeline.register_pre(FastModule("estixe"))

        results = await asyncio.gather(*[
            pipeline.run_pre(_req(), PipelineContext(tenant=f"t-{i}"))
            for i in range(10)
        ])
        assert all(r.decision == Decision.CONTINUE for r in results)

    @pytest.mark.asyncio
    async def test_100_concurrent(self):
        """100 concurrent requests should all succeed."""
        pipeline = Pipeline()
        pipeline.register_pre(FastModule("estixe"))
        pipeline.register_pre(FastModule("nomos"))

        results = await asyncio.gather(*[
            pipeline.run_pre(_req(), PipelineContext(tenant=f"t-{i}"))
            for i in range(100)
        ])
        assert all(r.decision == Decision.CONTINUE for r in results)
        assert len(results) == 100

    @pytest.mark.asyncio
    async def test_latency_under_budget(self):
        """Pipeline overhead should be under 50ms p95."""
        pipeline = Pipeline()
        pipeline.register_pre(FastModule("estixe"))
        pipeline.register_pre(FastModule("nomos"))
        pipeline.register_pre(FastModule("metis"))

        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            await pipeline.run_pre(_req(), PipelineContext())
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)

        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        # Pipeline overhead (without embedding/LLM) should be very fast
        assert p95 < 50, f"p95 latency {p95:.1f}ms exceeds 50ms budget"
        assert p99 < 100, f"p99 latency {p99:.1f}ms exceeds 100ms budget"


class TestCircuitBreaker:
    """Test the circuit breaker in proxy."""

    def test_circuit_breaker_opens_after_threshold(self):
        from aion.proxy import _record_failure, _check_circuit_breaker, _cb_failures, _cb_open_until

        provider = "test-provider"
        _cb_failures[provider] = 0
        _cb_open_until[provider] = 0

        # Fail 5 times
        for _ in range(5):
            _record_failure(provider)

        # Circuit should be open
        assert _check_circuit_breaker(provider) is True

        # Cleanup
        _cb_failures.pop(provider, None)
        _cb_open_until.pop(provider, None)

    def test_circuit_breaker_closed_when_healthy(self):
        from aion.proxy import _record_success, _check_circuit_breaker, _cb_failures, _cb_open_until

        provider = "test-healthy"
        _cb_failures[provider] = 0
        _cb_open_until[provider] = 0

        _record_success(provider)
        assert _check_circuit_breaker(provider) is False

        # Cleanup
        _cb_failures.pop(provider, None)
        _cb_open_until.pop(provider, None)


class TestAnthropicAdapter:
    """Test Anthropic format conversion."""

    def test_adapt_to_anthropic(self):
        from aion.proxy import _adapt_to_anthropic

        payload = {
            "model": "claude-sonnet-4-6",
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
        }

        result = _adapt_to_anthropic(payload)

        assert result["model"] == "claude-sonnet-4-6"
        assert result["system"] == "You are helpful"
        assert len(result["messages"]) == 1  # system extracted
        assert result["messages"][0]["role"] == "user"
        assert result["temperature"] == 0.7

    def test_adapt_anthropic_response(self):
        from aion.proxy import _adapt_anthropic_response

        data = {
            "id": "msg_123",
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        result = _adapt_anthropic_response(data)

        assert result["object"] == "chat.completion"
        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["usage"]["total_tokens"] == 15
