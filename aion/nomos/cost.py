"""Cost estimator — estimates token cost for a request/response pair."""

from __future__ import annotations

from aion.nomos.registry import ModelConfig


def estimate_prompt_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English, ~3 for Portuguese)."""
    return max(1, len(text) // 3)


def estimate_request_cost(
    model: ModelConfig,
    prompt_tokens: int,
    completion_tokens: int = 0,
) -> float:
    """Estimate cost in USD for a request."""
    input_cost = (prompt_tokens / 1000) * model.cost_per_1k_input
    output_cost = (completion_tokens / 1000) * model.cost_per_1k_output
    return round(input_cost + output_cost, 8)


def estimate_savings(
    original_model: ModelConfig,
    routed_model: ModelConfig,
    prompt_tokens: int,
    completion_tokens: int = 200,
) -> float:
    """Estimate cost savings from routing to a cheaper model."""
    original_cost = estimate_request_cost(original_model, prompt_tokens, completion_tokens)
    routed_cost = estimate_request_cost(routed_model, prompt_tokens, completion_tokens)
    return max(0, round(original_cost - routed_cost, 8))
