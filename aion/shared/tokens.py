"""Shared token utilities — single source of truth for token counting and message extraction."""

from __future__ import annotations

from typing import Optional

from aion.shared.schemas import ChatCompletionRequest, ChatMessage

# Try tiktoken for accurate counting, fallback to heuristic
try:
    import tiktoken
    _encoder = tiktoken.get_encoding("cl100k_base")
    _USE_TIKTOKEN = True
except Exception:
    _encoder = None
    _USE_TIKTOKEN = False


def count_tokens_text(text: str) -> int:
    """Count tokens in a text string."""
    if not text:
        return 0
    if _USE_TIKTOKEN and _encoder:
        return len(_encoder.encode(text))
    # Fallback: ~3.5 chars per token (Portuguese/English average)
    return max(1, len(text) // 3)


def count_tokens_request(request: ChatCompletionRequest) -> int:
    """Count total tokens in a chat completion request."""
    total = 0
    for msg in request.messages:
        total += 4  # message overhead (role, separators)
        if msg.content:
            total += count_tokens_text(msg.content)
        if msg.name:
            total += count_tokens_text(msg.name)
    total += 2  # reply priming
    return max(1, total)


def extract_user_message(request: ChatCompletionRequest) -> Optional[str]:
    """Extract the last user message from the conversation."""
    for msg in reversed(request.messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return None
