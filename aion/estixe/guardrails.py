"""Guardrails — PII detection and filtering for input AND output.

Covers international + Brazilian PII patterns:
- Email, phone, credit card, SSN (international)
- CPF, CNPJ, RG, chave PIX, CEP (Brazilian)
- Generic secrets (API keys, tokens, passwords in text)

v1.5: Hybrid NER — regex fast-path + semantic context check to reduce
false positives. "formato de CPF e 123.456.789-00" is NOT real PII.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from aion.config import get_estixe_settings
from aion.shared.contracts import PiiAction, PiiPolicyConfig

logger = logging.getLogger("aion.estixe.guardrails")

# ── PII Patterns ──
# International
_PII_PATTERNS = [
    # Credit card (must be checked BEFORE phone to avoid false positives)
    (r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b", "credit_card"),
    (r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))\d{8,12}\b", "credit_card"),
    # Phone (international formats)
    (r"\b\+?\d{1,3}[-.\s]?\(?\d{2,3}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}\b", "phone_number"),
    # Brazilian phone — DDD in parentheses, 8-digit landline or 9-digit mobile
    (r"\(\d{2}\)\s*\d{4,5}-\d{4}", "phone_number"),
    # SSN (US)
    (r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b", "ssn"),
    # Email
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email"),
    # Date of birth
    (r"\b\d{2}[./]\d{2}[./]\d{4}\b", "date_of_birth"),

    # ── Brazilian PII ──
    # CPF: 000.000.000-00, 00000000000, 000 000 000 00, 000-000-000-00 — aceita . - espaço em qualquer posição
    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{2}\b", "cpf"),
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
    blocked: bool = False
    block_reason: str = ""
    audited: list[str] = None  # PII types detected in audit mode

    def __post_init__(self):
        if self.violations is None:
            self.violations = []
        if self.audited is None:
            self.audited = []


class Guardrails:
    """PII and sensitive content guardrails for input AND output.

    v1.5: Hybrid NER — regex detects candidates, context check filters false positives.
    If context check is unavailable, falls back to pure regex (v1 behavior).
    """

    def __init__(self) -> None:
        self._pii_patterns = [
            (re.compile(p, re.IGNORECASE), name) for p, name in _PII_PATTERNS
        ]
        self._settings = get_estixe_settings()
        self._exclusion_embeddings: Optional[list] = None  # lazy loaded
        self._exclusion_texts: list[str] = []
        self._context_check_ready = False

    async def load_exclusions(self, config_dir: Optional[Path] = None) -> None:
        """Load PII exclusion contexts and pre-compute embeddings."""
        if config_dir is None:
            from aion.config import get_settings
            config_dir = get_settings().config_dir

        path = config_dir / "pii_exclusions.yaml"
        if not path.exists():
            logger.debug("No PII exclusions file found: %s", path)
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._exclusion_texts = data.get("exclusion_contexts", [])
        if not self._exclusion_texts:
            return

        try:
            from aion.shared.embeddings import get_embedding_model
            model = get_embedding_model()
            if not model.loaded:
                await model.load()
            self._exclusion_embeddings = model.encode(
                self._exclusion_texts, normalize=True
            )
            self._context_check_ready = True
            logger.info("PII context check loaded: %d exclusion patterns", len(self._exclusion_texts))
        except Exception:
            logger.warning("Could not load PII exclusion embeddings — using regex only", exc_info=True)

    def _is_false_positive(self, content: str, match_start: int, match_end: int) -> bool:
        """Check if a regex PII match is a false positive based on surrounding context.

        Extracts a window around the match, embeds it, and checks similarity
        against exclusion anchors. High similarity = false positive.
        """
        if not self._context_check_ready or self._exclusion_embeddings is None:
            return False  # fail-safe: assume real PII

        # Extract context window: 60 chars before + 60 chars after
        ctx_start = max(0, match_start - 60)
        ctx_end = min(len(content), match_end + 60)
        context_window = content[ctx_start:ctx_end].strip()

        if not context_window:
            return False

        try:
            from aion.shared.embeddings import get_embedding_model
            model = get_embedding_model()
            ctx_embedding = model.encode_single(context_window, normalize=True)

            # Check similarity with exclusion patterns
            similarities = self._exclusion_embeddings @ ctx_embedding
            max_sim = float(max(similarities))

            if max_sim > 0.65:
                logger.debug(
                    '{"event":"pii_false_positive","context":"%s","max_sim":%.3f}',
                    context_window[:50], max_sim,
                )
                return True
        except Exception:
            pass  # fail-safe: treat as real PII

        return False

    def check_output(
        self, content: str, pii_policy: PiiPolicyConfig | None = None,
    ) -> GuardrailResult:
        """Check content for PII with per-type policy actions.

        Actions per PII type (resolved via *pii_policy*):
          ALLOW — detect but don't modify content
          MASK  — replace with [TYPE_REDACTED] (default / backward-compat)
          BLOCK — reject the entire request
          AUDIT — detect, don't modify, but record in audited list
        """
        if content is None:
            return GuardrailResult(safe=True, violations=[], filtered_content="")

        result = GuardrailResult(filtered_content=content)
        policy = pii_policy or PiiPolicyConfig()  # default: mask everything

        for pattern, pii_type in self._pii_patterns:
            match = pattern.search(content)
            if not match:
                continue

            # v1.5: Context check — skip if this is a false positive
            if self._context_check_ready and self._is_false_positive(
                content, match.start(), match.end()
            ):
                continue  # false positive — not real PII

            action = policy.action_for(pii_type)
            result.violations.append(f"pii:{pii_type}")
            result.safe = False

            if action == PiiAction.MASK:
                result.filtered_content = pattern.sub(
                    f"[{pii_type.upper()}_REDACTED]", result.filtered_content,
                )
            elif action == PiiAction.BLOCK:
                result.blocked = True
                result.block_reason = f"PII type '{pii_type}' is blocked by policy"
                logger.warning(
                    '{"event":"pii_blocked","pii_type":"%s"}', pii_type,
                )
                return result  # early exit on block
            elif action == PiiAction.AUDIT:
                result.audited.append(pii_type)
                # don't modify content — just log
            # PiiAction.ALLOW — detected but no action taken

        if not result.safe:
            logger.warning(
                '{"event":"pii_detected","violation_count":%d,"audited":%d}',
                len(result.violations),
                len(result.audited),
            )

        return result

    def check_token_limit(self, prompt_tokens: int) -> bool:
        return prompt_tokens <= self._settings.max_tokens_per_request

    def reload(self) -> dict:
        """Recompila patterns PII a partir de _PII_PATTERNS no modulo.

        Uso:
            - Dev: edita guardrails.py (adicionar/alterar regex), chama endpoint
              POST /v1/estixe/guardrails/reload, novos patterns ativos sem restart.
            - Prod: redeploy reseta naturalmente; endpoint fica util em scenarios
              onde patterns vem de external source (v2 roadmap).

        Retorna summary para API response.
        """
        import importlib
        from aion.estixe import guardrails as _self_module
        importlib.reload(_self_module)
        # Re-pega a lista nova do modulo recarregado
        self._pii_patterns = [
            (re.compile(p, re.IGNORECASE), name)
            for p, name in _self_module._PII_PATTERNS
        ]
        return {
            "status": "reloaded",
            "pattern_count": len(self._pii_patterns),
            "pattern_types": sorted({name for _, name in self._pii_patterns}),
        }
