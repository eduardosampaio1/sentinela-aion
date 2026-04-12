"""Chaos tests — verify system survives component failures.

Tests real failure scenarios:
- Module crash → others continue
- LLM unreachable → proper error
- Pipeline total failure → fail-open passthrough
"""

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


class CrashModule:
    def __init__(self, name, error_msg="crash!"):
        self.name = name
        self._error_msg = error_msg
    async def process(self, request, context):
        raise RuntimeError(self._error_msg)


class SlowModule:
    def __init__(self, name, delay=0.1):
        self.name = name
        self._delay = delay
    async def process(self, request, context):
        import asyncio
        await asyncio.sleep(self._delay)
        context.metadata[f"{self.name}_called"] = True
        return context


class TrackingModule:
    def __init__(self, name):
        self.name = name
        self.call_count = 0
    async def process(self, request, context):
        self.call_count += 1
        return context


def _req(content="test"):
    return ChatCompletionRequest(
        model="test", messages=[ChatMessage(role="user", content=content)]
    )


class TestChaosModuleCrash:
    """Module crashes should NOT bring down the pipeline."""

    @pytest.mark.asyncio
    async def test_first_module_crash_others_run(self):
        pipeline = Pipeline()
        pipeline.register_pre(CrashModule("estixe"))
        nomos = TrackingModule("nomos")
        metis = TrackingModule("metis")
        pipeline.register_pre(nomos)
        pipeline.register_pre(metis)

        ctx = await pipeline.run_pre(_req(), PipelineContext())
        assert ctx.decision == Decision.CONTINUE
        assert nomos.call_count == 1
        assert metis.call_count == 1

    @pytest.mark.asyncio
    async def test_middle_module_crash_others_run(self):
        pipeline = Pipeline()
        estixe = TrackingModule("estixe")
        pipeline.register_pre(estixe)
        pipeline.register_pre(CrashModule("nomos"))
        metis = TrackingModule("metis")
        pipeline.register_pre(metis)

        ctx = await pipeline.run_pre(_req(), PipelineContext())
        assert estixe.call_count == 1
        assert metis.call_count == 1
        assert "nomos" in ctx.metadata.get("failed_modules", [])

    @pytest.mark.asyncio
    async def test_all_modules_crash_still_passthrough(self):
        pipeline = Pipeline()
        pipeline.register_pre(CrashModule("estixe"))
        pipeline.register_pre(CrashModule("nomos"))
        pipeline.register_pre(CrashModule("metis"))

        ctx = await pipeline.run_pre(_req(), PipelineContext())
        # Decision should be CONTINUE (fail-open → passthrough to LLM)
        assert ctx.decision == Decision.CONTINUE
        assert len(ctx.metadata.get("failed_modules", [])) == 3

    @pytest.mark.asyncio
    async def test_post_module_crash_returns_original_response(self):
        pipeline = Pipeline()
        pipeline.register_post(CrashModule("metis"))

        resp = ChatCompletionResponse(
            model="test",
            choices=[ChatCompletionChoice(
                message=ChatMessage(role="assistant", content="original"),
            )],
        )
        result = await pipeline.run_post(resp, PipelineContext())
        # Original response preserved
        assert result.choices[0].message.content == "original"


class TestChaosAutoDegrade:
    """Modules auto-degrade after repeated failures."""

    @pytest.mark.asyncio
    async def test_module_degrades_after_threshold(self):
        pipeline = Pipeline()
        pipeline.register_pre(CrashModule("estixe"))
        tracker = TrackingModule("nomos")
        pipeline.register_pre(tracker)

        # Fail 3 times (threshold)
        for _ in range(3):
            await pipeline.run_pre(_req(), PipelineContext())

        # ESTIXE should be degraded now
        assert not pipeline._module_status["estixe"].healthy

        # On next call, ESTIXE is SKIPPED (not even attempted)
        tracker.call_count = 0
        ctx = await pipeline.run_pre(_req(), PipelineContext())
        assert tracker.call_count == 1
        assert "estixe" in ctx.metadata.get("skipped_modules", [])
        assert "estixe" not in ctx.metadata.get("failed_modules", [])  # not failed, skipped

    @pytest.mark.asyncio
    async def test_degraded_module_shows_in_health(self):
        pipeline = Pipeline()
        pipeline.register_pre(CrashModule("estixe"))
        pipeline.register_pre(TrackingModule("nomos"))

        for _ in range(3):
            await pipeline.run_pre(_req(), PipelineContext())

        health = pipeline.get_health()
        assert health["mode"] == "degraded"
        assert "estixe" in health["degraded_components"]
        assert health["modules"]["nomos"] == "ok"


class TestChaosConcurrent:
    """Concurrent requests should not corrupt state."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_no_corruption(self):
        import asyncio

        pipeline = Pipeline()
        pipeline.register_pre(SlowModule("estixe", delay=0.01))
        pipeline.register_pre(TrackingModule("nomos"))

        async def run_one(i):
            ctx = PipelineContext(tenant=f"tenant-{i}")
            return await pipeline.run_pre(_req(f"query {i}"), ctx)

        # Run 20 concurrent requests
        results = await asyncio.gather(*[run_one(i) for i in range(20)])

        # All should succeed
        for r in results:
            assert r.decision == Decision.CONTINUE

        # Each should have its own tenant
        tenants = {r.tenant for r in results}
        assert len(tenants) == 20
