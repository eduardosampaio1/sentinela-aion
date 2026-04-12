"""Complexity classifier — scores prompt complexity using heuristics.

No ML model needed — uses fast heuristics to estimate how "hard" a prompt is.
Complexity score ranges from 0 (trivial) to 100 (very complex).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Indicators of complex prompts
_COMPLEXITY_PATTERNS = [
    # Reasoning / analysis
    (r"\b(explain|analyze|compare|evaluate|assess|reason|think|consider)\b", 10),
    (r"\b(why|how does|what if|suppose|assume|hypothetically)\b", 8),
    # Multi-step
    (r"\b(step by step|first.*then|multiple|several|list all)\b", 12),
    (r"\b(and also|additionally|furthermore|moreover)\b", 5),
    # Code / technical
    (r"\b(code|function|implement|algorithm|debug|refactor|optimize)\b", 15),
    (r"\b(class|def |import |return |async |await )\b", 15),
    (r"```", 20),  # code blocks
    # Creative / generation
    (r"\b(write|create|generate|compose|draft|design)\b", 10),
    (r"\b(essay|article|story|report|document|specification)\b", 12),
    # Math / logic
    (r"\b(calculate|compute|solve|prove|derive|formula)\b", 12),
    (r"[+\-*/=<>]{2,}", 5),  # math operators
    # Structured output
    (r"\b(json|xml|yaml|csv|table|format as)\b", 8),
    (r"\b(translate|convert|transform)\b", 8),
]

# Indicators of simple prompts
_SIMPLICITY_PATTERNS = [
    (r"^\w+\?$", -20),  # single word question
    (r"^(yes|no|ok|sure|thanks)\b", -30),
    (r"^(what is|who is|where is|when was)\b", -10),
]


@dataclass
class ComplexityResult:
    score: float  # 0-100
    factors: list[str]


class ComplexityClassifier:
    """Scores prompt complexity using fast heuristics."""

    def classify(self, messages: list[dict]) -> ComplexityResult:
        """Classify the complexity of a conversation.

        Considers the last user message primarily, with context from history.
        """
        # Get the last user message (supports both dict and object)
        user_message = ""
        for msg in reversed(messages):
            role = msg.role if hasattr(msg, "role") else msg.get("role", "")
            content = (msg.content if hasattr(msg, "content") else msg.get("content", "")) or ""
            if role == "user":
                user_message = content
                break

        if not user_message:
            return ComplexityResult(score=0, factors=["no_user_message"])

        score = 0.0
        factors = []

        # Length-based scoring
        word_count = len(user_message.split())
        if word_count > 200:
            score += 20
            factors.append(f"long_prompt({word_count}w)")
        elif word_count > 50:
            score += 10
            factors.append(f"medium_prompt({word_count}w)")
        elif word_count < 5:
            score -= 10
            factors.append(f"short_prompt({word_count}w)")

        # Pattern-based scoring
        text_lower = user_message.lower()
        for pattern, weight in _COMPLEXITY_PATTERNS:
            if re.search(pattern, text_lower):
                score += weight
                factors.append(f"pattern:{pattern[:20]}")

        for pattern, weight in _SIMPLICITY_PATTERNS:
            if re.search(pattern, text_lower):
                score += weight  # weight is negative
                factors.append(f"simple:{pattern[:20]}")

        # Conversation length factor
        msg_count = len(messages)
        if msg_count > 10:
            score += 10
            factors.append(f"long_conversation({msg_count})")

        # System prompt complexity
        for msg in messages:
            role = msg.role if hasattr(msg, "role") else msg.get("role", "")
            content = (msg.content if hasattr(msg, "content") else msg.get("content", "")) or ""
            if role == "system" and len(content) > 500:
                score += 10
                factors.append("complex_system_prompt")
                break

        # Clamp to 0-100
        score = max(0, min(100, score))

        return ComplexityResult(score=round(score, 1), factors=factors)
