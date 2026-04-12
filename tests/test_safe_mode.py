"""Tests for SAFE_MODE (killswitch) and per-component degradation.

These are APPROVAL GATE tests:
1. SAFE_MODE must actually bypass everything
2. Component degradation must prove isolation
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from aion.pipeline import Pipeline, ModuleStatus, build_pipeline
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    Decision,
    PipelineContext,
    UsageInfo,
)


# ──────────────────────────────────────────────
# Module stubs for testing
# ──────────────────────────────────────────────

class TrackingModule:
    """Module that records it was called."""
    def __init__(self, name: str):
        self.name = name
        self.call_count = 0

    async def process(self, request, context):
        self.call_count += 1
        context.metadata[f"{self.name}_called"] = True
        return context


class FailingModule:
    """Module that always raises an exception."""
    def __init__(self, name: str):
        self.name = name

    async def process(self, request, context):
        raise RuntimeError(f"{self.name} crashed!")


class BypassModule:
    """Module that sets bypass response."""
    def __init__(self, name: str):
        self.name = name

    async def process(self, request, context):
        resp = ChatCompletionResponse(
            model="bypass-test",
            choices=[ChatCompletionChoice(
                message=ChatMessage(role="assistant", content="bypassed"),
            )],
        )
        context.set_bypass(resp)
        return context


def _make_request(content="test"):
    return ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content=content)],
    )


# ══════════════════════════════════════════════
# TEST 1: SAFE_MODE BYPASSES EVERYTHING
# ══════════════════════════════════════════════

class TestSafeMode:
    """SAFE_MODE = kill switch. When active, AION is invisible."""

    @pytest.mark.asyncio
    async def test_safe_mode_skips_all_pre_modules(self):
        """With SAFE_MODE on, no pre-LLM module should be called."""
        pipeline = Pipeline()
        estixe = TrackingModule("estixe")
        nomos = TrackingModule("nomos")
        metis = TrackingModule("metis")
        pipeline.register_pre(estixe)
        pipeline.register_pre(nomos)
        pipeline.register_pre(metis)

        # Activate SAFE_MODE
        pipeline.activate_safe_mode("test")

        ctx = PipelineContext()
        result = await pipeline.run_pre(_make_request(), ctx)

        # NO module was called
        assert estixe.call_count == 0
        assert nomos.call_count == 0
        assert metis.call_count == 0

        # Decision remains CONTINUE (passthrough to LLM)
        assert result.decision == Decision.CONTINUE

        # Safe mode flag in metadata
        assert result.metadata.get("safe_mode") is True

    @pytest.mark.asyncio
    async def test_safe_mode_skips_all_post_modules(self):
        """Post-LLM modules are also skipped in SAFE_MODE."""
        pipeline = Pipeline()
        metis_post = TrackingModule("metis")
        pipeline.register_post(metis_post)
        pipeline.activate_safe_mode("test")

        response = ChatCompletionResponse(
            model="test", choices=[ChatCompletionChoice(
                message=ChatMessage(role="assistant", content="original"),
            )],
        )

        result = await pipeline.run_post(response, PipelineContext())

        # Post module NOT called
        assert metis_post.call_count == 0
        # Response unchanged
        assert result.choices[0].message.content == "original"

    @pytest.mark.asyncio
    async def test_safe_mode_activate_deactivate(self):
        """Kill switch can be toggled."""
        pipeline = Pipeline()
        mod = TrackingModule("estixe")
        pipeline.register_pre(mod)

        # Normal mode
        assert not pipeline.is_safe_mode
        ctx1 = PipelineContext()
        await pipeline.run_pre(_make_request(), ctx1)
        assert mod.call_count == 1

        # Activate SAFE_MODE
        pipeline.activate_safe_mode("incident")
        assert pipeline.is_safe_mode
        ctx2 = PipelineContext()
        await pipeline.run_pre(_make_request(), ctx2)
        assert mod.call_count == 1  # still 1 — not called

        # Deactivate
        pipeline.deactivate_safe_mode()
        assert not pipeline.is_safe_mode
        ctx3 = PipelineContext()
        await pipeline.run_pre(_make_request(), ctx3)
        assert mod.call_count == 2  # called again

    @pytest.mark.asyncio
    async def test_safe_mode_health_reports_correctly(self):
        """Health endpoint reflects SAFE_MODE status."""
        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))

        # Normal
        health = pipeline.get_health()
        assert health["mode"] == "normal"

        # Safe mode
        pipeline.activate_safe_mode("llm_instability")
        health = pipeline.get_health()
        assert health["mode"] == "safe"
        assert health["safe_mode_reason"] == "llm_instability"
        assert health["modules"]["estixe"] == "bypassed"

    @pytest.mark.asyncio
    async def test_safe_mode_headers_are_coherent(self):
        """Degradation headers correctly report SAFE_MODE state."""
        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))
        pipeline.register_pre(TrackingModule("nomos"))
        pipeline.activate_safe_mode("test")

        headers = pipeline.get_degraded_headers()
        assert headers["X-Aion-Degraded"] == "true"
        assert headers["X-Aion-Degraded-Components"] == "all"
        assert headers["X-Aion-Degraded-Impact"] == "passthrough"

    @pytest.mark.asyncio
    async def test_safe_mode_via_env_config(self):
        """SAFE_MODE can be activated via AION_SAFE_MODE env var."""
        import aion.config
        aion.config._settings = None
        with patch.dict(os.environ, {"AION_SAFE_MODE": "true"}):
            aion.config._settings = None
            pipeline = build_pipeline()
            assert pipeline.is_safe_mode

            ctx = PipelineContext()
            result = await pipeline.run_pre(_make_request(), ctx)
            assert result.decision == Decision.CONTINUE
            assert result.metadata.get("safe_mode") is True

        # Cleanup
        aion.config._settings = None


# ══════════════════════════════════════════════
# TEST 2: PER-COMPONENT DEGRADATION
# ══════════════════════════════════════════════

class TestComponentDegradation:
    """When a module fails, ONLY that module is disabled. Others continue."""

    @pytest.mark.asyncio
    async def test_estixe_fails_nomos_continues(self):
        """If ESTIXE crashes, NOMOS still runs."""
        pipeline = Pipeline()
        estixe = FailingModule("estixe")
        nomos = TrackingModule("nomos")
        pipeline.register_pre(estixe)
        pipeline.register_pre(nomos)

        # First request: ESTIXE fails, NOMOS runs (fail-open)
        ctx = PipelineContext()
        result = await pipeline.run_pre(_make_request(), ctx)

        assert result.decision == Decision.CONTINUE
        assert nomos.call_count == 1
        assert "estixe" in result.metadata.get("failed_modules", [])

    @pytest.mark.asyncio
    async def test_degraded_module_auto_skipped_after_threshold(self):
        """After N consecutive failures, module is auto-degraded and skipped."""
        pipeline = Pipeline()
        estixe = FailingModule("estixe")
        nomos = TrackingModule("nomos")
        pipeline.register_pre(estixe)
        pipeline.register_pre(nomos)

        # Fail 3 times (threshold)
        for i in range(3):
            ctx = PipelineContext()
            await pipeline.run_pre(_make_request(), ctx)
            assert nomos.call_count == i + 1

        # Now ESTIXE should be marked as degraded
        status = pipeline._module_status["estixe"]
        assert not status.healthy

        # Next request: ESTIXE is SKIPPED (not even attempted), NOMOS runs
        nomos.call_count = 0
        ctx = PipelineContext()
        result = await pipeline.run_pre(_make_request(), ctx)
        assert nomos.call_count == 1
        assert "estixe" in result.metadata.get("skipped_modules", [])

    @pytest.mark.asyncio
    async def test_nomos_fails_estixe_and_metis_continue(self):
        """If NOMOS crashes, ESTIXE and METIS still run."""
        pipeline = Pipeline()
        estixe = TrackingModule("estixe")
        nomos = FailingModule("nomos")
        metis = TrackingModule("metis")
        pipeline.register_pre(estixe)
        pipeline.register_pre(nomos)
        pipeline.register_pre(metis)

        ctx = PipelineContext()
        result = await pipeline.run_pre(_make_request(), ctx)

        assert estixe.call_count == 1  # ran before NOMOS
        assert metis.call_count == 1   # ran after NOMOS (skipped)
        assert "nomos" in result.metadata.get("failed_modules", [])

    @pytest.mark.asyncio
    async def test_health_reflects_degraded_component(self):
        """Health endpoint shows which component is degraded."""
        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))
        pipeline.register_pre(TrackingModule("nomos"))

        # Manually degrade NOMOS
        pipeline._module_status["nomos"].healthy = False

        health = pipeline.get_health()
        assert health["mode"] == "degraded"
        assert "nomos" in health["degraded_components"]
        assert health["modules"]["estixe"] == "ok"
        assert health["modules"]["nomos"] == "degraded"

    @pytest.mark.asyncio
    async def test_degraded_headers_reflect_component(self):
        """Response headers correctly identify which component is degraded."""
        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))
        pipeline.register_pre(TrackingModule("nomos"))

        pipeline._module_status["nomos"].healthy = False

        headers = pipeline.get_degraded_headers()
        assert headers["X-Aion-Degraded"] == "true"
        assert "nomos" in headers["X-Aion-Degraded-Components"]
        assert "routing_fallback" in headers["X-Aion-Degraded-Impact"]

        # ESTIXE is NOT in degraded components
        assert "estixe" not in headers["X-Aion-Degraded-Components"]

    @pytest.mark.asyncio
    async def test_no_degradation_no_headers(self):
        """When all modules healthy, no degradation headers."""
        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))
        pipeline.register_pre(TrackingModule("nomos"))

        headers = pipeline.get_degraded_headers()
        assert len(headers) == 0

    @pytest.mark.asyncio
    async def test_module_recovers_after_success(self):
        """A degraded module recovers when it succeeds again."""
        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))

        # Force degradation
        pipeline._module_status["estixe"].healthy = False
        pipeline._module_status["estixe"].consecutive_failures = 5

        # Manually recover
        pipeline._module_status["estixe"].record_success()
        assert pipeline._module_status["estixe"].healthy is True
        assert pipeline._module_status["estixe"].consecutive_failures == 0


# ══════════════════════════════════════════════
# TEST 3: API-LEVEL KILLSWITCH
# ══════════════════════════════════════════════

class TestKillswitchAPI:
    """Test killswitch via HTTP endpoints."""

    @pytest.fixture
    async def client(self):
        from aion.main import app
        import aion.main as main_mod
        # Ensure pipeline is built for test
        if main_mod._pipeline is None:
            main_mod._pipeline = build_pipeline()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
        # Cleanup: deactivate safe mode after test
        if main_mod._pipeline:
            main_mod._pipeline.deactivate_safe_mode()

    @pytest.mark.asyncio
    async def test_killswitch_activate_and_request(self, client):
        """Activate killswitch via API, then verify request goes through as passthrough."""
        # Activate
        resp = await client.put("/v1/killswitch", json={"reason": "llm_instability"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "safe_mode_active"

        # Health reflects safe mode
        health = await client.get("/health")
        assert health.json()["mode"] == "safe"

        # Chat request with mocked LLM
        mock_response = ChatCompletionResponse(
            model="gpt-4o-mini",
            choices=[ChatCompletionChoice(
                message=ChatMessage(role="assistant", content="direct from LLM"),
            )],
            usage=UsageInfo(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )
        with patch("aion.main.forward_request", new_callable=AsyncMock) as mock_fwd:
            mock_fwd.return_value = mock_response
            resp = await client.post("/v1/chat/completions", json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "test"}],
            })
            assert resp.status_code == 200
            assert resp.json()["choices"][0]["message"]["content"] == "direct from LLM"
            assert resp.headers.get("x-aion-decision") == "passthrough"
            assert resp.headers.get("x-request-id") is not None

            # LLM was called (not bypassed)
            mock_fwd.assert_called_once()

        # Deactivate
        resp = await client.delete("/v1/killswitch")
        assert resp.status_code == 200
        assert resp.json()["status"] == "normal_mode_restored"

        # Health back to normal
        health = await client.get("/health")
        # Mode depends on whether modules initialized, but not "safe" anymore
        assert health.json().get("mode") != "safe"
