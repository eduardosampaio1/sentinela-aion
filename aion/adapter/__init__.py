"""aion.adapter — ExecutionAdapter facade.

AION Core produces a DecisionContract; the ExecutionAdapter consumes it
and executes the appropriate action. Transparent/Assisted modes call
``execute()``. Decision mode never touches this module.
"""

from __future__ import annotations

import logging

from aion.adapter.approval_executor import ApprovalExecutor
from aion.adapter.base import ActionExecutor, ExecutionResult
from aion.adapter.block_executor import BlockExecutor
from aion.adapter.bypass_executor import BypassExecutor
from aion.adapter.llm_executor import LLMExecutor
from aion.adapter.service_executor import ServiceExecutor
from aion.contract.decision import Action, DecisionContract

logger = logging.getLogger("aion.adapter")


class ExecutionAdapter:
    """Dispatches a DecisionContract to the right ActionExecutor."""

    def __init__(self) -> None:
        bypass = BypassExecutor()
        block = BlockExecutor()
        llm = LLMExecutor()
        service = ServiceExecutor()
        approval = ApprovalExecutor()

        self._executors: dict[Action, ActionExecutor] = {
            Action.CALL_LLM: llm,
            Action.CALL_SERVICE: service,
            Action.BYPASS: bypass,
            Action.RETURN_RESPONSE: bypass,  # same behavior as BYPASS
            Action.BLOCK: block,
            Action.REQUEST_HUMAN_APPROVAL: approval,
        }

    async def execute(
        self, contract: DecisionContract, stream: bool = False,
    ) -> ExecutionResult:
        executor = self._executors.get(contract.action)
        if executor is None:
            from aion.contract.errors import ContractError, ErrorType
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.INVALID_REQUEST,
                    detail=f"Unsupported action: {contract.action}",
                ),
                status_code=500,
            )
        return await executor.execute(contract, stream)

    async def close(self) -> None:
        """Cleanup resources (HTTP clients, etc.)."""
        svc = self._executors.get(Action.CALL_SERVICE)
        if isinstance(svc, ServiceExecutor):
            await svc.close()


_instance: ExecutionAdapter | None = None


def get_adapter() -> ExecutionAdapter:
    global _instance
    if _instance is None:
        _instance = ExecutionAdapter()
    return _instance


__all__ = [
    "ActionExecutor",
    "ExecutionAdapter",
    "ExecutionResult",
    "get_adapter",
]
