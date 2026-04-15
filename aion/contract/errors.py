"""Contract error types — standardized across all integration modes."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ErrorType(str, Enum):
    """Standardized error categories surfaced in the contract.

    Mapped to HTTP status codes by the caller:
        invalid_request  -> 400
        unauthorized     -> 401
        policy_violation -> 403
        rate_limit       -> 429
        upstream_error   -> 502/503 (if retryable=True)
        timeout          -> 504
    """
    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    POLICY_VIOLATION = "policy_violation"
    RATE_LIMIT = "rate_limit"
    UPSTREAM_ERROR = "upstream_error"
    TIMEOUT = "timeout"


_DEFAULT_STATUS = {
    ErrorType.INVALID_REQUEST: 400,
    ErrorType.UNAUTHORIZED: 401,
    ErrorType.POLICY_VIOLATION: 403,
    ErrorType.RATE_LIMIT: 429,
    ErrorType.UPSTREAM_ERROR: 502,
    ErrorType.TIMEOUT: 504,
}


class ContractError(BaseModel):
    """Error expressed inside the DecisionContract.

    HTTP status is derived from ``type`` via ``status_code()``.
    """
    type: ErrorType
    retryable: bool = False
    fallback_used: bool = False
    detail: Optional[str] = None

    def status_code(self) -> int:
        base = _DEFAULT_STATUS[self.type]
        # upstream_error with retryable=True hints 503 (temporary) vs 502 (permanent)
        if self.type == ErrorType.UPSTREAM_ERROR and self.retryable:
            return 503
        return base
