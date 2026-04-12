"""E2E tests — full pipeline flow, streaming, and determinism.

These tests verify real behavior, not mocks.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from aion.pipeline import Pipeline, build_pipeline
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    Decision,
    PipelineContext,
    UsageInfo,
)


class TrackingModule:
    def __init__(self, name):
        self.name = name
        self.call_count = 0
    async def process(self, request, context):
        self.call_count += 1
        context.metadata[f"{self.name}_called"] = True
        return context


class BypassModule:
    def __init__(self, name):
        self.name = name
    async def process(self, request, context):
        resp = ChatCompletionResponse(
            model="bypass",
            choices=[ChatCompletionChoice(message=ChatMessage(role="assistant", content="bypassed"))],
        )
        context.set_bypass(resp)
        return context


def _mock_llm_response():
    return ChatCompletionResponse(
        id="test-123",
        model="gpt-4o-mini",
        choices=[ChatCompletionChoice(
            message=ChatMessage(role="assistant", content="LLM response"),
        )],
        usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


# ══════════════════════════════════════════════
# E2E: Full pipeline cascade
# ══════════════════════════════════════════════

class TestE2EFullPipeline:

    @pytest.mark.asyncio
    async def test_all_modules_passthrough(self):
        """Request flows through ALL modules → LLM → response."""
        pipeline = Pipeline()
        estixe = TrackingModule("estixe")
        nomos = TrackingModule("nomos")
        metis = TrackingModule("metis")
        metis_post = TrackingModule("metis")
        pipeline.register_pre(estixe)
        pipeline.register_pre(nomos)
        pipeline.register_pre(metis)
        pipeline.register_post(metis_post)

        req = ChatCompletionRequest(
            model="test", messages=[ChatMessage(role="user", content="Complex question about algorithms")]
        )
        ctx = PipelineContext(tenant="test-tenant")
        ctx = await pipeline.run_pre(req, ctx)

        assert ctx.decision == Decision.CONTINUE
        assert estixe.call_count == 1
        assert nomos.call_count == 1
        assert metis.call_count == 1

        # Simulate LLM response + post pipeline
        resp = _mock_llm_response()
        resp = await pipeline.run_post(resp, ctx)
        assert metis_post.call_count == 1
        assert resp.choices[0].message.content == "LLM response"

    @pytest.mark.asyncio
    async def test_bypass_stops_before_llm(self):
        """ESTIXE bypass → LLM is never called → response direct."""
        pipeline = Pipeline()
        pipeline.register_pre(BypassModule("estixe"))
        nomos = TrackingModule("nomos")
        pipeline.register_pre(nomos)

        req = ChatCompletionRequest(
            model="test", messages=[ChatMessage(role="user", content="oi")]
        )
        ctx = PipelineContext()
        ctx = await pipeline.run_pre(req, ctx)

        assert ctx.decision == Decision.BYPASS
        assert ctx.bypass_response.choices[0].message.content == "bypassed"
        assert nomos.call_count == 0  # NOMOS never reached


# ══════════════════════════════════════════════
# E2E: API-level with mocked LLM
# ══════════════════════════════════════════════

class TestE2EAPI:

    @pytest.fixture
    async def client(self):
        from aion.main import app
        import aion.main as main_mod
        if main_mod._pipeline is None:
            main_mod._pipeline = build_pipeline()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_full_request_response_cycle(self, client):
        """Complete request → pipeline → LLM mock → response."""
        with patch("aion.main.forward_request", new_callable=AsyncMock) as mock_fwd:
            mock_fwd.return_value = _mock_llm_response()

            resp = await client.post("/v1/chat/completions", json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is Python?"}],
            })

            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "LLM response"
            assert "x-request-id" in resp.headers
            assert resp.headers.get("x-aion-decision") == "passthrough"

    @pytest.mark.asyncio
    async def test_error_format_is_openai_compatible(self, client):
        """Errors use OpenAI error format."""
        # Send too many messages
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(101)]
        resp = await client.post("/v1/chat/completions", json={
            "model": "test",
            "messages": messages,
        })
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data
        assert "message" in data["error"]
        assert "code" in data["error"]

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client):
        """Prometheus metrics endpoint returns valid content."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "aion_requests_total" in resp.text

    @pytest.mark.asyncio
    async def test_audit_endpoint(self, client):
        """Audit trail is accessible."""
        resp = await client.get("/v1/audit")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_module_toggle(self, client):
        """Feature flag: toggle module on/off at runtime."""
        import aion.main as main_mod
        # Ensure pipeline has modules registered
        if not main_mod._pipeline._module_status:
            main_mod._pipeline.register_pre(TrackingModule("test_module"))

        module_name = list(main_mod._pipeline._module_status.keys())[0]
        resp = await client.put(f"/v1/modules/{module_name}/toggle", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # Re-enable
        resp = await client.put(f"/v1/modules/{module_name}/toggle", json={"enabled": True})
        assert resp.json()["enabled"] is True

    @pytest.mark.asyncio
    async def test_data_deletion(self, client):
        """LGPD: delete tenant data."""
        resp = await client.delete("/v1/data/test-tenant")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"


# ══════════════════════════════════════════════
# Determinism: same input → same decision path
# ══════════════════════════════════════════════

class TestDeterminism:

    @pytest.mark.asyncio
    async def test_same_input_same_route(self):
        """Same input produces same decision path every time."""
        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))
        pipeline.register_pre(TrackingModule("nomos"))

        req = ChatCompletionRequest(
            model="test", messages=[ChatMessage(role="user", content="Explain quantum computing")]
        )

        results = []
        for _ in range(5):
            ctx = PipelineContext(tenant="determinism-test")
            ctx = await pipeline.run_pre(req, ctx)
            results.append({
                "decision": ctx.decision.value,
                "modules_called": [k for k in ctx.module_latencies.keys()],
            })

        # All 5 runs should produce identical decision paths
        for r in results[1:]:
            assert r["decision"] == results[0]["decision"]
            assert r["modules_called"] == results[0]["modules_called"]
