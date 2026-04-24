"""Base types shared by all executors."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunResult:
    """Result of running a single benchmark prompt through an executor."""
    prompt_id: str
    tier: str
    category: str
    prompt: str
    response_text: str
    expected_pattern: str

    called_llm: bool = False
    action: str = "CALL_LLM"   # CALL_LLM | BYPASS | BLOCK

    total_latency_ms: float = 0.0
    decision_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
