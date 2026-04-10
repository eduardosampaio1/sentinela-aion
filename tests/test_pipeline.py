"""Tests for the pipeline orchestrator."""

import pytest

from aion.pipeline import Pipeline
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    Decision,
    PipelineContext,
)


class MockBypassModule:
    name = "mock_bypass"

    async def process(self, request, context):
        resp = ChatCompletionResponse(
            model="mock",
            choices=[ChatCompletionChoice(
                message=ChatMessage(role="assistant", content="Bypassed!")
            )],
        )
        context.set_bypass(resp)
        return context


class MockPassthroughModule:
    name = "mock_passthrough"

    async def process(self, request, context):
        return context


class MockBlockModule:
    name = "mock_block"

    async def process(self, request, context):
        context.set_block("Test block")
        return context


class MockFailingModule:
    name = "mock_failing"

    async def process(self, request, context):
        raise RuntimeError("Module crashed!")


def _make_request(content="test"):
    return ChatCompletionRequest(
        model="test",
        messages=[ChatMessage(role="user", content=content)],
    )


@pytest.mark.asyncio
async def test_empty_pipeline():
    pipeline = Pipeline()
    ctx = PipelineContext()
    result = await pipeline.run_pre(_make_request(), ctx)
    assert result.decision == Decision.CONTINUE


@pytest.mark.asyncio
async def test_bypass_module():
    pipeline = Pipeline()
    pipeline.register_pre(MockBypassModule())

    ctx = PipelineContext()
    result = await pipeline.run_pre(_make_request(), ctx)
    assert result.decision == Decision.BYPASS
    assert result.bypass_response.choices[0].message.content == "Bypassed!"


@pytest.mark.asyncio
async def test_block_module():
    pipeline = Pipeline()
    pipeline.register_pre(MockBlockModule())

    ctx = PipelineContext()
    result = await pipeline.run_pre(_make_request(), ctx)
    assert result.decision == Decision.BLOCK


@pytest.mark.asyncio
async def test_bypass_stops_chain():
    """If first module bypasses, second module should NOT run."""
    pipeline = Pipeline()
    pipeline.register_pre(MockBypassModule())
    pipeline.register_pre(MockBlockModule())  # should not be reached

    ctx = PipelineContext()
    result = await pipeline.run_pre(_make_request(), ctx)
    assert result.decision == Decision.BYPASS  # not BLOCK


@pytest.mark.asyncio
async def test_passthrough_then_bypass():
    pipeline = Pipeline()
    pipeline.register_pre(MockPassthroughModule())
    pipeline.register_pre(MockBypassModule())

    ctx = PipelineContext()
    result = await pipeline.run_pre(_make_request(), ctx)
    assert result.decision == Decision.BYPASS


@pytest.mark.asyncio
async def test_failing_module_fail_open():
    """In fail-open mode, a crashing module should be skipped."""
    import os
    os.environ["AION_FAIL_MODE"] = "open"

    # Reset settings singleton
    import aion.config
    aion.config._settings = None

    pipeline = Pipeline()
    pipeline.register_pre(MockFailingModule())
    pipeline.register_pre(MockPassthroughModule())

    ctx = PipelineContext()
    result = await pipeline.run_pre(_make_request(), ctx)
    assert result.decision == Decision.CONTINUE  # skipped failing module
    assert "mock_failing" in result.module_latencies


@pytest.mark.asyncio
async def test_module_latency_tracking():
    pipeline = Pipeline()
    pipeline.register_pre(MockPassthroughModule())

    ctx = PipelineContext()
    result = await pipeline.run_pre(_make_request(), ctx)
    assert "mock_passthrough" in result.module_latencies
    assert result.module_latencies["mock_passthrough"] >= 0
