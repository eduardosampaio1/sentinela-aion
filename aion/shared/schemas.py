"""Shared schemas — OpenAI-compatible request/response + AION internals."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# OpenAI-compatible chat completion schemas
# ──────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible /v1/chat/completions request."""
    model: str
    messages: list[ChatMessage]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    stream: Optional[bool] = False
    stop: Optional[str | list[str]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None
    # Pass-through for provider-specific fields
    model_config = {"extra": "allow"}


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: Optional[str] = "stop"


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    id: str = Field(default_factory=lambda: f"aion-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[ChatCompletionChoice] = []
    usage: Optional[UsageInfo] = None


class StreamChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class StreamChunkChoice(BaseModel):
    index: int = 0
    delta: StreamChunkDelta
    finish_reason: Optional[str] = None


class ChatCompletionStreamChunk(BaseModel):
    """OpenAI-compatible streaming chunk."""
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[StreamChunkChoice] = []


# ──────────────────────────────────────────────
# AION pipeline internals
# ──────────────────────────────────────────────

class Decision(str, Enum):
    """Module decision outcome."""
    CONTINUE = "continue"   # pass to next module
    BYPASS = "bypass"       # respond directly, skip LLM
    BLOCK = "block"         # refuse request


class ModuleName(str, Enum):
    ESTIXE = "estixe"
    NOMOS = "nomos"
    METIS = "metis"


class PipelineContext(BaseModel):
    """Mutable context that flows through the pipeline."""
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    tenant: str = "default"
    original_request: Optional[ChatCompletionRequest] = None
    modified_request: Optional[ChatCompletionRequest] = None
    decision: Decision = Decision.CONTINUE
    bypass_response: Optional[ChatCompletionResponse] = None
    selected_model: Optional[str] = None
    selected_provider: Optional[str] = None
    selected_base_url: Optional[str] = None
    tokens_before: int = 0
    tokens_after: int = 0
    module_latencies: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # --- Multi-turn session tracking ---
    session_id: Optional[str] = None  # derived from tenant + first message anchor

    # --- Formal module results (populated alongside metadata for backward compat) ---
    # Typed as Any to avoid circular import with aion.shared.contracts. Each module
    # populates its respective result instance; metadata is the legacy/extensibility
    # surface and remains authoritative for telemetry whitelists.
    estixe_result: Optional[Any] = None
    nomos_result: Optional[Any] = None
    metis_result: Optional[Any] = None

    def set_bypass(self, response: ChatCompletionResponse) -> None:
        self.decision = Decision.BYPASS
        self.bypass_response = response

    def set_block(self, reason: str) -> None:
        self.decision = Decision.BLOCK
        self.metadata["block_reason"] = reason
