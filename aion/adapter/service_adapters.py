"""Service response adapters — translate service dict → ChatCompletionResponse.

Each adapter is referenced by name in config/services.yaml via
``response_adapter``. If absent, ServiceExecutor falls back to a minimal
template that wraps the raw dict as JSON content.
"""

from __future__ import annotations

import json
import time
from typing import Callable

from aion.shared.schemas import (
    ChatCompletionChoice,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)


def default_adapter(raw: dict, service_name: str) -> ChatCompletionResponse:
    """Fallback adapter — wraps raw dict as assistant content."""
    content = json.dumps(raw, ensure_ascii=False) if not isinstance(raw, str) else raw
    return ChatCompletionResponse(
        id=f"svc-{service_name}-{int(time.time())}",
        model=f"service:{service_name}",
        created=int(time.time()),
        choices=[ChatCompletionChoice(
            index=0,
            message=ChatMessage(role="assistant", content=content),
            finish_reason="stop",
        )],
        usage=UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


# Registry of named adapters — extend as more services are onboarded.
_ADAPTERS: dict[str, Callable[[dict, str], ChatCompletionResponse]] = {}


def register_adapter(name: str, func: Callable[[dict, str], ChatCompletionResponse]) -> None:
    _ADAPTERS[name] = func


def get_adapter(name: str | None) -> Callable[[dict, str], ChatCompletionResponse]:
    if name and name in _ADAPTERS:
        return _ADAPTERS[name]
    return default_adapter
