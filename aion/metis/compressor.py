"""Prompt compressor — reduces token usage before sending to LLM.

Strategies:
- Remove duplicate/redundant system instructions
- Compress conversation history (keep last N turns, summarize rest)
- Remove excessive whitespace
- Deduplicate repeated content across messages
"""

from __future__ import annotations

import re
from typing import Optional

from aion.config import MetisSettings
from aion.shared.schemas import ChatCompletionRequest, ChatMessage


class PromptCompressor:
    """Compresses prompts to reduce token usage."""

    def __init__(self, settings: MetisSettings) -> None:
        self._settings = settings

    def compress(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        """Apply all compression strategies to the request."""
        if not self._settings.compression_enabled:
            return request

        messages = list(request.messages)

        # Strategy 1: Clean whitespace in all messages
        messages = [self._clean_whitespace(m) for m in messages]

        # Strategy 2: Deduplicate system instructions
        messages = self._dedup_system_instructions(messages)

        # Strategy 3: Trim conversation history
        messages = self._trim_history(messages)

        compressed = request.model_copy(deep=True)
        compressed.messages = messages
        return compressed

    def count_tokens(self, request: ChatCompletionRequest) -> int:
        """Count tokens using shared utility (tiktoken if available)."""
        from aion.shared.tokens import count_tokens_request
        return count_tokens_request(request)

    @staticmethod
    def _clean_whitespace(message: ChatMessage) -> ChatMessage:
        """Remove excessive whitespace from message content."""
        if not message.content:
            return message
        cleaned = re.sub(r"\n{3,}", "\n\n", message.content)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = cleaned.strip()
        if cleaned != message.content:
            return ChatMessage(
                role=message.role,
                content=cleaned,
                name=message.name,
                tool_calls=message.tool_calls,
                tool_call_id=message.tool_call_id,
            )
        return message

    @staticmethod
    def _dedup_system_instructions(messages: list[ChatMessage]) -> list[ChatMessage]:
        """Merge duplicate system messages."""
        system_messages = [m for m in messages if m.role == "system"]
        if len(system_messages) <= 1:
            return messages

        # Merge all system messages into one
        combined_content = "\n\n".join(
            m.content for m in system_messages if m.content
        )
        # Deduplicate lines
        seen_lines = set()
        unique_lines = []
        for line in combined_content.split("\n"):
            stripped = line.strip()
            if stripped and stripped not in seen_lines:
                seen_lines.add(stripped)
                unique_lines.append(line)
            elif not stripped:
                unique_lines.append(line)

        merged = ChatMessage(role="system", content="\n".join(unique_lines))

        # Replace: put merged system message first, remove duplicates
        result = [merged]
        for m in messages:
            if m.role != "system":
                result.append(m)
        return result

    def _trim_history(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Keep only the last N turns of conversation history."""
        max_turns = self._settings.max_history_turns

        # Separate system messages from conversation
        system_msgs = [m for m in messages if m.role == "system"]
        conv_msgs = [m for m in messages if m.role != "system"]

        if len(conv_msgs) <= max_turns * 2:
            return messages

        # Keep the last N turns (user+assistant pairs)
        trimmed_conv = conv_msgs[-(max_turns * 2):]

        return system_msgs + trimmed_conv
