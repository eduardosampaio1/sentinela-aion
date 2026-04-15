"""ActionExecutor protocol + ExecutionResult — standardized adapter output."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from aion.contract.decision import Action, DecisionContract
from aion.contract.errors import ContractError
from aion.shared.schemas import ChatCompletionResponse


class ExecutionResult(BaseModel):
    """Standardized output from any ActionExecutor.

    The Adapter produces ExecutionResult. HTTP layer converts it to a
    JSONResponse or StreamingResponse, adding headers derived from the
    contract.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    response: Optional[ChatCompletionResponse] = None
    raw_service_response: Optional[dict] = None
    stream_iterator: Optional[Any] = None  # AsyncIterator[str] when streaming
    status_code: int = 200
    headers: dict[str, str] = Field(default_factory=dict)
    error: Optional[ContractError] = None
    executed_in_ms: float = 0.0
    provider_metadata: dict = Field(default_factory=dict)


@runtime_checkable
class ActionExecutor(Protocol):
    """Interface every executor implements."""

    action: Action

    async def execute(
        self, contract: DecisionContract, stream: bool = False,
    ) -> ExecutionResult:
        ...
