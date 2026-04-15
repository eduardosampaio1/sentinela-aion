"""BypassExecutor — executes BYPASS and RETURN_RESPONSE actions.

Both actions share behavior: a ChatCompletionResponse is already cached
in the contract's final_output.payload.response — just return it.
"""

from __future__ import annotations

import json
import time
from typing import AsyncIterator

from aion.adapter.base import ActionExecutor, ExecutionResult
from aion.contract.decision import Action, DecisionContract
from aion.contract.errors import ContractError, ErrorType
from aion.shared.schemas import (
    ChatCompletionResponse,
    ChatCompletionStreamChunk,
    StreamChunkChoice,
    StreamChunkDelta,
)


class BypassExecutor:
    """Handles BYPASS and RETURN_RESPONSE — response is already built."""

    action = Action.BYPASS

    async def execute(
        self, contract: DecisionContract, stream: bool = False,
    ) -> ExecutionResult:
        t0 = time.perf_counter()

        payload = contract.final_output.payload if contract.final_output else {}
        response_dict = payload.get("response")
        if not response_dict:
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.INVALID_REQUEST,
                    detail="Bypass contract missing response payload",
                ),
                status_code=500,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )

        response = ChatCompletionResponse(**response_dict)

        if stream:
            return ExecutionResult(
                success=True,
                response=response,
                stream_iterator=_bypass_stream(response),
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )

        return ExecutionResult(
            success=True,
            response=response,
            executed_in_ms=(time.perf_counter() - t0) * 1000,
        )


async def _bypass_stream(response: ChatCompletionResponse) -> AsyncIterator[str]:
    """SSE stream that emits the bypass response as a single content chunk."""
    content = response.choices[0].message.content if response.choices else ""

    chunk = ChatCompletionStreamChunk(
        id=f"bypass-{int(time.time())}",
        model=response.model,
        choices=[StreamChunkChoice(
            index=0, delta=StreamChunkDelta(role="assistant", content=content),
        )],
    )
    yield f"data: {json.dumps(chunk.model_dump())}\n\n"

    finish = ChatCompletionStreamChunk(
        id=chunk.id,
        model=response.model,
        choices=[StreamChunkChoice(
            index=0, delta=StreamChunkDelta(), finish_reason="stop",
        )],
    )
    yield f"data: {json.dumps(finish.model_dump())}\n\n"
    yield "data: [DONE]\n\n"
