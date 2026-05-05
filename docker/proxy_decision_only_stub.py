"""AION — Decision-Only build stub for aion/proxy.py.

F-38 (qa-ceifador P2.B): in the Decision-Only image, the upstream LLM proxy
is REMOVED at build time and replaced with this stub. The promise of POC
Decision-Only is "AION never calls the LLM, never receives credentials" —
this stub is the structural guarantee of that promise: even if a runtime
configuration error were to route a request through forward_request(), the
function would refuse to execute, returning a structured error.

Side note: aion/routers/proxy.py keeps both `/v1/decide` (Decision) and
`/v1/chat/completions` (Transparent) handlers. F-37 already returns 403
on `/v1/chat/completions` when AION_MODE=poc_decision; this F-38 stub is
defense-in-depth — it makes the Transparent path physically impossible
because the import would still resolve (the stub is the active proxy.py),
but the call would raise.

Compatibility: keeps the exact public surface of aion/proxy.py so module
loaders, type checkers, and `from aion.proxy import forward_request` calls
elsewhere in the codebase don't break at import time. They only break when
actually invoked — which is exactly the desired enforcement boundary.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger("aion.proxy.stub")


_DECISION_ONLY_ERROR = (
    "F-38: aion.proxy is disabled in this Decision-Only image. "
    "AION must not call the LLM. If you need /v1/chat/completions or /v1/chat/assisted, "
    "rebuild the image without --decision-only or use the standard docker/Dockerfile.aion."
)


class DecisionOnlyImageError(RuntimeError):
    """Raised when LLM-bound code is invoked in a Decision-Only build."""


def _refuse(name: str) -> None:
    logger.critical(
        "F-38: %s called in Decision-Only image — refusing to proceed. %s",
        name, _DECISION_ONLY_ERROR,
    )
    raise DecisionOnlyImageError(_DECISION_ONLY_ERROR)


# ── Public surface mirrored from aion/proxy.py ────────────────────────────────

async def forward_request(*args, **kwargs):
    """Stub — never calls the LLM. Always raises DecisionOnlyImageError."""
    _refuse("forward_request")


async def forward_request_stream(*args, **kwargs) -> AsyncIterator[str]:
    """Stub async-generator. Yields nothing; raises before first yield."""
    _refuse("forward_request_stream")
    if False:  # pragma: no cover — keeps the function a generator
        yield ""  # noqa: B901


async def shutdown_client() -> None:
    """Stub — no-op. Real proxy maintains an httpx client; here there is none."""
    return None


def build_bypass_stream(response):
    """Stub — bypass streams are built by the adapter layer, not aion.proxy.

    Kept for import compatibility. The Decision-Only adapter.bypass_executor
    handles bypass responses without going through this function.
    """
    _refuse("build_bypass_stream")
