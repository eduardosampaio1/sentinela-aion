"""Tests for CALL_SERVICE action — ServiceExecutor + registry + adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aion.adapter.registry import ServiceConfig, ServiceRegistry
from aion.adapter.service_adapters import (
    default_adapter,
    get_adapter,
    register_adapter,
)
from aion.adapter.service_executor import ServiceExecutor
from aion.contract.decision import (
    Action,
    ContractMeta,
    DecisionContract,
    FinalOutput,
    RetryPolicy,
)
from aion.shared.schemas import ChatCompletionResponse


def _contract(service_name: str | None, **payload_extras) -> DecisionContract:
    payload = {"service_name": service_name} if service_name else {}
    payload.update(payload_extras)
    return DecisionContract(
        request_id="req_1",
        action=Action.CALL_SERVICE,
        final_output=FinalOutput(
            target_type="service",
            payload=payload,
            retry_policy=RetryPolicy(max_retries=1, timeout_ms=1000),
        ),
        meta=ContractMeta(tenant="test", timestamp=0.0),
    )


# ── Registry ──

class TestServiceRegistry:
    @pytest.mark.asyncio
    async def test_load_from_yaml(self):
        registry = ServiceRegistry()
        await registry.load()
        # config/services.yaml has 'echo' as an example
        svc = registry.get("echo")
        assert svc is not None
        assert svc.name == "echo"
        assert "echo" in svc.capabilities

    @pytest.mark.asyncio
    async def test_unknown_service_returns_none(self):
        registry = ServiceRegistry()
        await registry.load()
        assert registry.get("nonexistent") is None


# ── Adapters ──

class TestServiceAdapters:
    def test_default_adapter_wraps_dict(self):
        raw = {"status": "ok", "data": [1, 2, 3]}
        response = default_adapter(raw, "test_service")
        assert isinstance(response, ChatCompletionResponse)
        assert response.model == "service:test_service"
        content = response.choices[0].message.content
        assert "ok" in content

    def test_register_and_get_adapter(self):
        def _custom(raw: dict, name: str) -> ChatCompletionResponse:
            return ChatCompletionResponse(
                model=f"custom:{name}",
                choices=[{
                    "index": 0,
                    "message": {"role": "assistant", "content": f"custom: {raw.get('x')}"},
                    "finish_reason": "stop",
                }],
            )
        register_adapter("custom_test", _custom)
        adapter = get_adapter("custom_test")
        result = adapter({"x": 42}, "svc")
        assert result.model == "custom:svc"

    def test_missing_adapter_returns_default(self):
        adapter = get_adapter("nonexistent_adapter_xyz")
        assert adapter is default_adapter


# ── ServiceExecutor ──

class TestServiceExecutor:
    @pytest.mark.asyncio
    async def test_missing_service_name_fails(self):
        executor = ServiceExecutor()
        result = await executor.execute(_contract(None))
        assert not result.success
        assert "service_name" in result.error.detail

    @pytest.mark.asyncio
    async def test_unregistered_service_fails(self):
        executor = ServiceExecutor()
        result = await executor.execute(_contract("not_a_real_service"))
        assert not result.success
        assert "not registered" in result.error.detail

    @pytest.mark.asyncio
    async def test_successful_call_returns_normalized_response(self):
        """Mock httpx to simulate a successful service call."""
        executor = ServiceExecutor()
        await executor._ensure_ready()

        # Inject a fake service
        executor._registry._services["fake_svc"] = ServiceConfig(
            name="fake_svc",
            endpoint="https://fake.local/api",
            method="POST",
            timeout_seconds=5,
        )

        mock_response = httpx.Response(
            200,
            json={"result": "hello", "count": 2},
            request=httpx.Request("POST", "https://fake.local/api"),
        )

        with patch.object(executor._client, "request", new=AsyncMock(return_value=mock_response)):
            contract = _contract("fake_svc", body={"q": "ping"})
            result = await executor.execute(contract)

        assert result.success
        assert result.response is not None
        assert result.response.model == "service:fake_svc"
        # Raw response preserved
        assert result.raw_service_response == {"result": "hello", "count": 2}

    @pytest.mark.asyncio
    async def test_failed_call_returns_upstream_error(self):
        executor = ServiceExecutor()
        await executor._ensure_ready()

        executor._registry._services["fail_svc"] = ServiceConfig(
            name="fail_svc",
            endpoint="https://fail.local/api",
            timeout_seconds=1,
        )

        error_response = httpx.Response(
            500,
            json={"error": "boom"},
            request=httpx.Request("POST", "https://fail.local/api"),
        )
        err = httpx.HTTPStatusError("Server Error", request=error_response.request, response=error_response)

        async def _raise(*args, **kwargs):
            raise err

        with patch.object(executor._client, "request", new=_raise):
            contract = _contract("fail_svc", body={})
            result = await executor.execute(contract)

        assert not result.success
        assert result.error.type.value == "upstream_error"
