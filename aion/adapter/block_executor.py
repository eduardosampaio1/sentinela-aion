"""BlockExecutor — renders BLOCK as a structured error response."""

from __future__ import annotations

import time

from aion.adapter.base import ActionExecutor, ExecutionResult
from aion.contract.decision import Action, DecisionContract
from aion.contract.errors import ContractError, ErrorType


class BlockExecutor:
    """Handles BLOCK action — returns a 403 with contract error."""

    action = Action.BLOCK

    async def execute(
        self, contract: DecisionContract, stream: bool = False,
    ) -> ExecutionResult:
        t0 = time.perf_counter()

        # Prefer the contract's error; fall back to payload reason.
        err = contract.error
        if err is None:
            reason = "Request blocked by policy"
            if contract.final_output:
                reason = contract.final_output.payload.get("reason", reason)
            err = ContractError(
                type=ErrorType.POLICY_VIOLATION,
                retryable=False,
                detail=reason,
            )

        return ExecutionResult(
            success=False,
            error=err,
            status_code=err.status_code(),
            executed_in_ms=(time.perf_counter() - t0) * 1000,
        )
