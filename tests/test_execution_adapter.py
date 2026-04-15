"""Tests for ExecutionAdapter + executors."""

from __future__ import annotations

import time

import pytest

from aion.adapter import ExecutionAdapter, ExecutionResult, get_adapter
from aion.adapter.block_executor import BlockExecutor
from aion.adapter.bypass_executor import BypassExecutor
from aion.contract.decision import (
    Action,
    ContractMeta,
    DecisionContract,
    FinalOutput,
)
from aion.contract.errors import ContractError, ErrorType
from aion.shared.schemas import (
    ChatCompletionChoice,
    ChatCompletionResponse,
    ChatMessage,
)


def _meta() -> ContractMeta:
    return ContractMeta(tenant="test", timestamp=time.time())


# ── BypassExecutor ──

class TestBypassExecutor:
    def _bypass_contract(self) -> DecisionContract:
        response = ChatCompletionResponse(
            model="aion-bypass",
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(role="assistant", content="hi"),
            )],
        )
        return DecisionContract(
            request_id="req_1",
            action=Action.BYPASS,
            final_output=FinalOutput(
                target_type="direct",
                payload={"response": response.model_dump()},
            ),
            meta=_meta(),
        )

    @pytest.mark.asyncio
    async def test_bypass_returns_response(self):
        executor = BypassExecutor()
        result = await executor.execute(self._bypass_contract())
        assert result.success
        assert result.response.choices[0].message.content == "hi"
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_bypass_stream(self):
        executor = BypassExecutor()
        result = await executor.execute(self._bypass_contract(), stream=True)
        assert result.success
        assert result.stream_iterator is not None

        chunks = []
        async for chunk in result.stream_iterator:
            chunks.append(chunk)
        joined = "".join(chunks)
        assert "hi" in joined
        assert "[DONE]" in joined

    @pytest.mark.asyncio
    async def test_bypass_missing_response_fails(self):
        executor = BypassExecutor()
        contract = DecisionContract(
            request_id="req_1",
            action=Action.BYPASS,
            final_output=FinalOutput(target_type="direct", payload={}),
            meta=_meta(),
        )
        result = await executor.execute(contract)
        assert not result.success
        assert result.error.type == ErrorType.INVALID_REQUEST


# ── BlockExecutor ──

class TestBlockExecutor:
    @pytest.mark.asyncio
    async def test_block_returns_403(self):
        executor = BlockExecutor()
        contract = DecisionContract(
            request_id="req_1",
            action=Action.BLOCK,
            final_output=FinalOutput(
                target_type="direct",
                payload={"reason": "prompt injection"},
            ),
            meta=_meta(),
        )
        result = await executor.execute(contract)
        assert not result.success
        assert result.status_code == 403
        assert result.error.type == ErrorType.POLICY_VIOLATION

    @pytest.mark.asyncio
    async def test_block_uses_contract_error_if_present(self):
        executor = BlockExecutor()
        contract = DecisionContract(
            request_id="req_1",
            action=Action.BLOCK,
            error=ContractError(type=ErrorType.UNAUTHORIZED, detail="bad key"),
            final_output=FinalOutput(target_type="direct", payload={}),
            meta=_meta(),
        )
        result = await executor.execute(contract)
        assert result.status_code == 401


# ── ApprovalExecutor ──

class TestApprovalExecutor:
    @pytest.mark.asyncio
    async def test_approval_creates_record(self):
        from aion.adapter.approval_executor import ApprovalExecutor, _approval_key
        executor = ApprovalExecutor()
        contract = DecisionContract(
            request_id="req_1",
            action=Action.REQUEST_HUMAN_APPROVAL,
            final_output=FinalOutput(
                target_type="human",
                payload={
                    "approval_request_id": "apr_test_1",
                    "on_timeout": "block",
                    "timeout_seconds": 3600,
                    "risk_level": "high",
                },
            ),
            meta=_meta(),
        )
        result = await executor.execute(contract)
        assert result.success
        assert result.status_code == 202
        assert result.headers.get("X-Aion-Approval-ID") == "apr_test_1"
        assert result.headers.get("X-Aion-Approval-Status") == "pending"

        # Record should be in NEMOS store
        from aion.nemos import get_nemos
        record = await get_nemos()._store.get_json(_approval_key("apr_test_1"))
        assert record is not None
        assert record["status"] == "pending"
        assert record["risk_level"] == "high"


# ── ExecutionAdapter facade ──

class TestExecutionAdapter:
    @pytest.mark.asyncio
    async def test_dispatches_bypass(self):
        adapter = ExecutionAdapter()
        response = ChatCompletionResponse(
            model="aion-bypass",
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(role="assistant", content="ok"),
            )],
        )
        contract = DecisionContract(
            request_id="req_1",
            action=Action.BYPASS,
            final_output=FinalOutput(
                target_type="direct",
                payload={"response": response.model_dump()},
            ),
            meta=_meta(),
        )
        result = await adapter.execute(contract)
        assert result.success

    @pytest.mark.asyncio
    async def test_dispatches_block(self):
        adapter = ExecutionAdapter()
        contract = DecisionContract(
            request_id="req_1",
            action=Action.BLOCK,
            final_output=FinalOutput(target_type="direct", payload={"reason": "nope"}),
            meta=_meta(),
        )
        result = await adapter.execute(contract)
        assert not result.success
        assert result.status_code == 403

    def test_singleton(self):
        a1 = get_adapter()
        a2 = get_adapter()
        assert a1 is a2

    @pytest.mark.asyncio
    async def test_return_response_same_as_bypass(self):
        """RETURN_RESPONSE uses BypassExecutor — same behavior."""
        adapter = ExecutionAdapter()
        response = ChatCompletionResponse(
            model="aion-return",
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(role="assistant", content="already_computed"),
            )],
        )
        contract = DecisionContract(
            request_id="req_1",
            action=Action.RETURN_RESPONSE,
            final_output=FinalOutput(
                target_type="direct",
                payload={"response": response.model_dump()},
            ),
            meta=_meta(),
        )
        result = await adapter.execute(contract)
        assert result.success
        assert result.response.choices[0].message.content == "already_computed"
