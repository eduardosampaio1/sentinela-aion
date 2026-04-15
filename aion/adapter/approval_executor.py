"""ApprovalExecutor — REQUEST_HUMAN_APPROVAL lifecycle (Phase E).

Creates an approval record in NEMOS and returns the contract with
polling_url + (optional) callback_url. Cliente faz poll em /v1/approvals/{id}
ate status != pending. Background sweep resolve timeouts via on_timeout.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from aion.adapter.base import ActionExecutor, ExecutionResult
from aion.contract.decision import Action, DecisionContract
from aion.contract.errors import ContractError, ErrorType
from aion.shared.schemas import (
    ChatCompletionChoice,
    ChatCompletionResponse,
    ChatMessage,
)

logger = logging.getLogger("aion.adapter.approval")

# Redis key helper
_APPROVAL_PREFIX = "aion:approval"
_APPROVAL_TTL = 7 * 86400  # 7 days


def _approval_key(approval_id: str) -> str:
    return f"{_APPROVAL_PREFIX}:{approval_id}"


class ApprovalExecutor:
    """Handles REQUEST_HUMAN_APPROVAL — creates pending approval and returns placeholder response."""

    action = Action.REQUEST_HUMAN_APPROVAL

    async def execute(
        self, contract: DecisionContract, stream: bool = False,
    ) -> ExecutionResult:
        t0 = time.perf_counter()

        payload = contract.final_output.payload if contract.final_output else {}
        approval_id = payload.get("approval_request_id") or f"apr_{uuid.uuid4().hex[:12]}"
        on_timeout = payload.get("on_timeout", "block")
        timeout_seconds = payload.get("timeout_seconds", 86400)  # default 24h
        risk_level = payload.get("risk_level", "medium")
        fallback_target = payload.get("fallback_target")

        now = time.time()
        expires_at = now + timeout_seconds

        approval_record: dict[str, Any] = {
            "approval_request_id": approval_id,
            "tenant": contract.meta.tenant,
            "status": "pending",
            "created_at": now,
            "expires_at": expires_at,
            "on_timeout": on_timeout,
            "risk_level": risk_level,
            "fallback_target": fallback_target,
            "original_request_id": contract.request_id,
            "polling_url": f"/v1/approvals/{approval_id}",
            "callback_url": payload.get("callback_url"),
            "resolved_by": None,
            "resolved_at": None,
        }

        # Persist in NEMOS store (graceful if NEMOS unavailable — returns ephemeral approval)
        try:
            from aion.nemos import get_nemos
            nemos = get_nemos()
            await nemos._store.set_json(_approval_key(approval_id), approval_record, ttl_seconds=_APPROVAL_TTL)
        except Exception:
            logger.warning("ApprovalExecutor: NEMOS store unavailable, approval is ephemeral")

        # Return a placeholder ChatCompletionResponse so clients see *something* in Transparent mode
        placeholder = ChatCompletionResponse(
            id=approval_id,
            model="aion-approval",
            created=int(now),
            choices=[ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=(
                        f"Aprovacao humana solicitada (id={approval_id}). "
                        f"Consulte /v1/approvals/{approval_id} para status."
                    ),
                ),
                finish_reason="stop",
            )],
        )

        return ExecutionResult(
            success=True,
            response=placeholder,
            status_code=202,  # accepted, pending
            headers={
                "X-Aion-Approval-ID": approval_id,
                "X-Aion-Approval-Status": "pending",
                "X-Aion-Approval-Expires-At": str(int(expires_at)),
            },
            executed_in_ms=(time.perf_counter() - t0) * 1000,
        )
