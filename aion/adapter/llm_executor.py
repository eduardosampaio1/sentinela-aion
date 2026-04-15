"""LLMExecutor — executes CALL_LLM by delegating to the existing proxy layer.

Reuses aion/proxy.py (forward_request / forward_request_stream) which already
handles circuit breaker, retry, provider adaptation (Anthropic), and streaming.
"""

from __future__ import annotations

import logging
import time
from typing import AsyncIterator

import httpx

from aion.adapter.base import ActionExecutor, ExecutionResult
from aion.config import get_settings
from aion.contract.decision import Action, DecisionContract
from aion.contract.errors import ContractError, ErrorType
from aion.proxy import forward_request, forward_request_stream
from aion.shared.schemas import ChatCompletionRequest, PipelineContext

logger = logging.getLogger("aion.adapter.llm")


class LLMExecutor:
    """Handles CALL_LLM — forwards to the selected provider via proxy.py."""

    action = Action.CALL_LLM

    async def execute(
        self, contract: DecisionContract, stream: bool = False,
    ) -> ExecutionResult:
        t0 = time.perf_counter()
        settings = get_settings()

        payload = contract.final_output.payload if contract.final_output else {}
        request_payload = payload.get("request_payload", {})
        try:
            request = ChatCompletionRequest(**request_payload)
        except Exception as exc:
            logger.exception("LLMExecutor: invalid request_payload")
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.INVALID_REQUEST,
                    detail=f"Invalid request_payload: {exc}",
                ),
                status_code=400,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )

        # Reconstruct a minimal PipelineContext — proxy.py uses it to resolve
        # provider/model/base_url when not overridden.
        ctx = PipelineContext(
            tenant=contract.meta.tenant,
            request_id=contract.request_id,
            selected_provider=payload.get("provider"),
            selected_model=payload.get("model"),
            selected_base_url=payload.get("base_url"),
        )

        try:
            if stream:
                async def _wrap_stream() -> AsyncIterator[str]:
                    async for chunk in forward_request_stream(request, ctx, settings):
                        yield chunk

                return ExecutionResult(
                    success=True,
                    stream_iterator=_wrap_stream(),
                    executed_in_ms=(time.perf_counter() - t0) * 1000,
                )

            response = await forward_request(request, ctx, settings)
            return ExecutionResult(
                success=True,
                response=response,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
                provider_metadata={"provider": payload.get("provider"), "model": payload.get("model")},
            )

        except httpx.HTTPStatusError as e:
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.UPSTREAM_ERROR,
                    retryable=e.response.status_code in (429, 500, 502, 503, 504),
                    detail=str(e),
                ),
                status_code=e.response.status_code,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            logger.exception("LLMExecutor unexpected failure")
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.UPSTREAM_ERROR,
                    retryable=False,
                    detail=f"Failed to reach LLM provider: {exc}",
                ),
                status_code=502,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )
