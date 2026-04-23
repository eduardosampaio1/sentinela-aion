"""Shared executor primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RunResult:
    """Result of executing a single prompt in a benchmark run."""
    prompt_id: str
    tier: str
    category: str
    prompt: str
    response_text: str
    expected_pattern: str

    # Latency breakdown
    decision_latency_ms: float = 0.0    # AION pre-LLM pipeline (0 for baseline)
    execution_latency_ms: float = 0.0   # LLM/service call time
    total_latency_ms: float = 0.0

    # Cost & tokens
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    # Decision (only populated for with_aion runs)
    called_llm: bool = True             # False when bypass/block
    action: str = "CALL_LLM"             # BYPASS | BLOCK | CALL_LLM | CALL_SERVICE
    model_used: str = ""
    decision_confidence: float = 0.0

    # Error
    error: Optional[str] = None

    # Arbitrary provider metadata (kept small, not summed in reports)
    metadata: dict = field(default_factory=dict)
