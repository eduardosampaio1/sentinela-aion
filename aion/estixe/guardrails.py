"""Guardrails — PII detection and filtering for input AND output.

Covers international + Brazilian PII patterns:
- Email, phone, credit card, SSN (international)
- CPF, CNPJ, RG, chave PIX, CEP (Brazilian)
- Generic secrets (API keys, tokens, passwords in text)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from aion.config import get_estixe_settings

logger = logging.getLogger("aion.estixe.guardrails")

# ── PII Patterns ──
# International
_PII_PATTERNS = [
    # Credit card (must be checked BEFORE phone to avoid false positives)
    (r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b", "credit_card"),
    (r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))\d{8,12}\b", "credit_card"),
    # Phone (international formats)
    (r"\b\+?\d{1,3}[-.\s]?\(?\d{2,3}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}\b", "phone_number"),
    # SSN (US)
    (r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b", "ssn"),
    # Email
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email"),
    # Date of birth
    (r"\b\d{2}[./]\d{2}[./]\d{4}\b", "date_of_birth"),

    # ── Brazilian PII ──
    # CPF: 000.000.000-00 or 00000000000
    (r"\b\d{3}\.?\d{3}\.?\d{3}[-.]?\d{2}\b", "cpf"),
    # CNPJ: 00.000.000/0000-00 or 00000000000000
    (r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}[-.]?\d{2}\b", "cnpj"),
    # RG (common formats: 00.000.000-0 or MG-00.000.000)
    (r"\b(?:[A-Z]{2}[-.]?)?\d{2}\.?\d{3}\.?\d{3}[-.]?\d{1,2}\b", "rg"),
    # CEP: 00000-000
    (r"\b\d{5}[-]?\d{3}\b", "cep"),
    # Chave PIX — UUID format
    (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "pix_key_uuid"),
    # Chave PIX — phone format (+55...)
    (r"\+55\d{2}\d{8,9}", "pix_key_phone"),
    # Chave PIX — random key (32 hex chars)
    (r"\b[0-9a-f]{32}\b", "pix_key_random"),

    # ── Generic secrets ──
    # API keys (common patterns: sk-..., pk_..., api-key-..., token_...)
    (r"\b(?:sk|pk)[-_][A-Za-z0-9_-]{16,}\b", "api_key"),
    (r"\b(?:api[-_]?key|token|secret)[-_:]?\s*[A-Za-z0-9_-]{20,}\b", "api_key"),
    # AWS access key
    (r"\bAKIA[0-9A-Z]{16}\b", "aws_key"),
    # Generic password-like patterns in text
    (r"\bpassw(?:ord|d)?[:=]\s*\S{6,}\b", "password_in_text"),
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
    """PII and sensitive content guardrails for input AND output."""

    def __init__(self) -> None:
        self._pii_patterns = [
            (re.compile(p, re.IGNORECASE), name) for p, name in _PII_PATTERNS
        ]
        self._settings = get_estixe_settings()

    def check_output(self, content: str) -> GuardrailResult:
        """Check content for PII (works for both input and output)."""
        result = GuardrailResult(filtered_content=content)

        for pattern, pii_type in self._pii_patterns:
            if pattern.search(content):
                result.violations.append(f"pii:{pii_type}")
                result.safe = False
                result.filtered_content = pattern.sub(
                    f"[{pii_type.upper()}_REDACTED]", result.filtered_content
                )

        if not result.safe:
            logger.warning(
                '{"event":"pii_detected","violation_count":%d}',
                len(result.violations),
            )

        return result

    def check_token_limit(self, prompt_tokens: int) -> bool:
        return prompt_tokens <= self._settings.max_tokens_per_request
