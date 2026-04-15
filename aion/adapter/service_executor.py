"""ServiceExecutor — executes CALL_SERVICE via the service registry.

Normalizes response to ChatCompletionResponse (OpenAI-compatible) via
the adapter registered for the service in config/services.yaml. Raw
response preserved in ``raw_service_response`` for Assisted mode.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from aion.adapter.base import ActionExecutor, ExecutionResult
from aion.adapter.registry import ServiceRegistry
from aion.adapter.service_adapters import get_adapter
from aion.contract.decision import Action, DecisionContract
from aion.contract.errors import ContractError, ErrorType

logger = logging.getLogger("aion.adapter.service")


class ServiceExecutor:
    """Handles CALL_SERVICE — calls internal/external APIs via registry."""

    action = Action.CALL_SERVICE

    def __init__(self) -> None:
        self._registry = ServiceRegistry()
        self._initialized = False
        self._client: httpx.AsyncClient | None = None

    async def _ensure_ready(self) -> None:
        if not self._initialized:
            await self._registry.load()
            self._initialized = True
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)

    async def execute(
        self, contract: DecisionContract, stream: bool = False,
    ) -> ExecutionResult:
        t0 = time.perf_counter()
        await self._ensure_ready()

        payload = contract.final_output.payload if contract.final_output else {}
        service_name = payload.get("service_name")
        if not service_name:
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.INVALID_REQUEST,
                    detail="CALL_SERVICE contract missing service_name",
                ),
                status_code=400,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )

        svc = self._registry.get(service_name)
        if not svc:
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.INVALID_REQUEST,
                    detail=f"Service '{service_name}' not registered",
                ),
                status_code=400,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )

        # Build request
        method = payload.get("method") or svc.method
        body = payload.get("body", {}) or {}
        headers = dict(payload.get("headers") or {})
        if svc.auth_env:
            token = os.environ.get(svc.auth_env)
            if token:
                headers.setdefault("Authorization", f"Bearer {token}")

        # Execute with retry from contract's retry_policy (if present)
        retry_policy = contract.final_output.retry_policy if contract.final_output else None
        max_retries = (retry_policy.max_retries if retry_policy else 2)
        timeout_s = (retry_policy.timeout_ms / 1000.0 if retry_policy else svc.timeout_seconds)

        last_error: Exception | None = None
        raw: dict | None = None
        status_code = 200

        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.request(
                    method, svc.endpoint,
                    json=body if method.upper() != "GET" else None,
                    params=body if method.upper() == "GET" else None,
                    headers=headers,
                    timeout=timeout_s,
                )
                status_code = resp.status_code
                resp.raise_for_status()
                raw = resp.json() if resp.content else {}
                break
            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                if status_code not in (429, 500, 502, 503, 504) or attempt == max_retries:
                    break
            except Exception as e:
                last_error = e
                if attempt == max_retries:
                    break

        if raw is None:
            return ExecutionResult(
                success=False,
                error=ContractError(
                    type=ErrorType.UPSTREAM_ERROR,
                    retryable=status_code in (429, 500, 502, 503, 504),
                    detail=f"Service '{service_name}' failed: {last_error}",
                ),
                status_code=status_code,
                executed_in_ms=(time.perf_counter() - t0) * 1000,
            )

        # Normalize response via adapter
        adapter = get_adapter(svc.response_adapter)
        response = adapter(raw, service_name)

        return ExecutionResult(
            success=True,
            response=response,
            raw_service_response=raw,  # Assisted/Decision mode can expose this
            executed_in_ms=(time.perf_counter() - t0) * 1000,
            provider_metadata={"service": service_name, "status_code": status_code},
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
