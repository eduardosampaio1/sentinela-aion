"""Output guard for ESTIXE — verifies LLM responses before delivery.

Two independent checks on every non-streaming LLM response:

    S2': PII in output  → MASK (replace) or BLOCK (reject)
         Catches personal data the model generated or reproduced from context.

    S3': Structural risk in output  → BLOCK
         Catches instruction/policy leakage: the model revealing its system prompt
         or internal guidelines in response to extraction attempts.

Chunking strategy (S3'):
    Embedding a full long response dilutes any single risky sentence. We split on
    sentence boundaries and classify each chunk independently, returning the
    highest-risk result. This prevents "benign padding" from lowering confidence
    below the threshold.

Streaming (v1.1):
    Streaming agora é coberto via buffer-accumulate-check-flush em main.py.
    Chunks são acumulados, texto completo é verificado por este OutputGuard, e
    então os chunks originais são emitidos ao cliente (ou substituídos por SSE
    de erro se bloqueado). Trade-off: cliente recebe todos os tokens de uma vez
    em vez de incrementalmente.
    V2 ideal: check incremental em janelas deslizantes para restaurar real UX.

Replacement boundary: OutputGuard.check() é agnóstico de fluxo (só precisa do texto
completo). Para evoluir v2 (incremental), substituir o wrapper em main.py, não aqui.
"""

from __future__ import annotations

import logging
import re

from aion.config import EstixeSettings
from aion.estixe.guardrails import Guardrails
from aion.estixe.risk_classifier import RiskClassifier, RiskMatch
from aion.shared.contracts import EstixeAction, EstixeResult, PiiPolicyConfig
from aion.shared.schemas import PipelineContext

logger = logging.getLogger("aion.estixe.output_guard")

# Minimum chunk length to classify — shorter strings are likely punctuation artifacts
_MIN_CHUNK_LEN = 15

# Sentence boundary split pattern
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+|\n+')


class OutputGuard:
    """Verifies LLM output for PII leakage and structural risk before delivery.

    Used by EstixeModule.check_llm_output() — call check() after receiving the
    LLM response, before returning it to the caller.
    """

    def __init__(
        self,
        guardrails: Guardrails,
        risk_classifier: RiskClassifier,
        settings: EstixeSettings,
    ) -> None:
        self._guardrails = guardrails
        self._risk_classifier = risk_classifier
        self._settings = settings

    async def check(
        self,
        response_text: str,
        context: PipelineContext,
    ) -> EstixeResult:
        """Check *response_text* for PII (S2') and structural risk (S3').

        Args:
            response_text: Raw text from the LLM (choices[0].message.content).
            context: Pipeline context — used to read PII policy and estixe_thresholds,
                     and to write filtered_llm_output / output_risk_* metadata.

        Returns:
            EstixeResult with action=CONTINUE (safe), action=BLOCK (reject), or
            action=CONTINUE + pii_sanitized=True (PII masked, filtered content in
            context.metadata["filtered_llm_output"]).
        """
        result = EstixeResult(action=EstixeAction.CONTINUE)

        if not response_text:
            return result

        pii_policy = self._resolve_pii_policy(context)

        # S2': PII in LLM output
        pii = self._guardrails.check_output(response_text, pii_policy=pii_policy)
        if pii.blocked:
            result.action = EstixeAction.BLOCK
            result.block_reason = pii.block_reason
            result.pii_violations = pii.violations
            logger.warning("OUTPUT BLOQUEADO: PII no response do LLM (%s)", pii.block_reason)
            return result
        if not pii.safe:
            context.metadata["filtered_llm_output"] = pii.filtered_content
            result.pii_violations = pii.violations
            result.pii_sanitized = True

        # S3': structural risk in LLM output
        # Velocity tightening is intentionally NOT applied here — output content
        # reflects what the model produced, not the attack pattern of the user.
        # Tenant threshold overrides still apply for sensitivity tuning.
        # Output threshold boost: output usa threshold mais rigoroso que input para
        # reduzir falsos positivos em respostas contendo termos sensiveis em contexto
        # benigno (ex: "fraude" em resposta sobre reportar fraude).
        if self._settings.risk_check_enabled:
            tenant_thresholds: dict[str, float] = (
                context.metadata.get("estixe_thresholds") or {}
            )
            boost = self._settings.output_threshold_boost
            # Aplica boost nas categorias: tenant override (se ja explicito) + base (categorias nao-custom)
            threshold_overrides: dict[str, float] = {}
            for r in self._risk_classifier._risks:
                base = tenant_thresholds.get(r.name, r.threshold)
                threshold_overrides[r.name] = min(0.99, base + boost)
            risk = self._classify_by_chunks(response_text, threshold_overrides)
            if risk is not None and not risk.shadow and risk.risk_level in ("critical", "high"):
                result.action = EstixeAction.BLOCK
                result.block_reason = (
                    f"Output bloqueado: resposta classifica como risco estrutural "
                    f"'{risk.category}' (confiança={risk.confidence:.2f})"
                )
                context.metadata["output_risk_category"] = risk.category
                context.metadata["output_risk_confidence"] = risk.confidence
                logger.warning(
                    "OUTPUT BLOQUEADO: risco estrutural '%s' (conf=%.3f) no response",
                    risk.category,
                    risk.confidence,
                )
                return result

        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    def _classify_by_chunks(
        self,
        text: str,
        threshold_overrides: dict[str, float] | None,
    ) -> RiskMatch | None:
        """Classify *text* by sentence chunks to prevent signal dilution.

        A risky sentence inside a long benign response scores below threshold
        when the full text is embedded — benign context dilutes the risk signal.
        Splitting by sentence boundaries and returning the highest-risk chunk
        result avoids this problem.
        """
        chunks = [c.strip() for c in _SENTENCE_BOUNDARY.split(text) if c.strip()]
        # Always include full text: catches cases where the entire response is risky
        candidates = chunks + [text] if len(chunks) > 1 else chunks

        best: RiskMatch | None = None
        for chunk in candidates:
            if len(chunk) < _MIN_CHUNK_LEN:
                continue
            match = self._risk_classifier.classify(
                chunk, threshold_overrides=threshold_overrides
            )
            if match is not None and (best is None or match.confidence > best.confidence):
                best = match

        return best

    @staticmethod
    def _resolve_pii_policy(context: PipelineContext) -> PiiPolicyConfig | None:
        """Resolve PII policy from context metadata."""
        raw = context.metadata.get("pii_policy")
        if raw is None:
            return None
        if isinstance(raw, PiiPolicyConfig):
            return raw
        if isinstance(raw, dict):
            return PiiPolicyConfig(**raw)
        return None
