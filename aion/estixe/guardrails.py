"""Guardrails — output filtering and token limits.

Monitors LLM responses for sensitive content and enforces limits.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from aion.config import get_estixe_settings

logger = logging.getLogger("aion.estixe.guardrails")

# Common PII patterns
_PII_PATTERNS = [
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "phone_number"),
    (r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b", "ssn"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email"),
    (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "credit_card"),
    (r"\b\d{2}[./]\d{2}[./]\d{4}\b", "date_of_birth"),
]


@dataclass
class GuardrailResult:
    """Result of guardrail check."""
    safe: bool = True
    violations: list[str] = None
    filtered_content: str = ""

    def __post_init__(self):
        if self.violations is None:
            self.violations = []


class Guardrails:
    """Output guardrails for LLM responses."""

    def __init__(self) -> None:
        self._pii_patterns = [
            (re.compile(p, re.IGNORECASE), name) for p, name in _PII_PATTERNS
        ]
        self._settings = get_estixe_settings()

    def check_output(self, content: str) -> GuardrailResult:
        """Check LLM output for PII and other sensitive content."""
        result = GuardrailResult(filtered_content=content)

        for pattern, pii_type in self._pii_patterns:
            if pattern.search(content):
                result.violations.append(f"pii:{pii_type}")
                result.safe = False
                # Mask the PII
                result.filtered_content = pattern.sub(
                    f"[{pii_type.upper()}_REDACTED]", result.filtered_content
                )

        if not result.safe:
            logger.warning("Guardrail violations detected: %s", result.violations)

        return result

    def check_token_limit(self, prompt_tokens: int) -> bool:
        """Check if request is within token limit."""
        return prompt_tokens <= self._settings.max_tokens_per_request
