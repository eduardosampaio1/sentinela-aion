"""ESTIXE — Control & Bypass Engine. Bloqueia, bypassa, aplica politica, reduz risco."""

from __future__ import annotations

import logging

from aion.config import get_estixe_settings
from aion.estixe.bypass import BypassEngine
from aion.estixe.classifier import SemanticClassifier
from aion.estixe.guardrails import Guardrails
from aion.estixe.policy import PolicyEngine
from aion.shared.contracts import PiiPolicyConfig
from aion.shared.schemas import ChatCompletionRequest, PipelineContext
from aion.shared.tokens import extract_user_message

logger = logging.getLogger("aion.estixe")


class EstixeModule:
    """ESTIXE pipeline module — runs classification, policy, and bypass."""

    name = "estixe"

    def __init__(self) -> None:
        settings = get_estixe_settings()
        self._classifier = SemanticClassifier(settings)
        self._bypass = BypassEngine(self._classifier)
        self._policy = PolicyEngine()
        self._guardrails = Guardrails()
        self._initialized = False

    async def initialize(self) -> None:
        if not self._initialized:
            await self._classifier.load()
            await self._policy.load()
            self._initialized = True
            logger.info("ESTIXE initialized")

    async def process(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        if not self._initialized:
            await self.initialize()

        # Extract user message using shared utility
        user_message = extract_user_message(request)
        if not user_message:
            return context

        # 0. PII guard on INPUT (not just output) — Track A1
        # Resolve per-tenant PII policy from context metadata
        pii_policy = self._resolve_pii_policy(context)
        input_check = self._guardrails.check_output(user_message, pii_policy=pii_policy)

        if input_check.blocked:
            context.set_block(input_check.block_reason)
            context.metadata["pii_violations"] = input_check.violations
            return context

        if not input_check.safe:
            logger.warning("PII detected in user input: %d violations", len(input_check.violations))
            context.metadata["pii_violations"] = input_check.violations
            if input_check.audited:
                context.metadata["pii_audited"] = input_check.audited
            # Sanitize input before proceeding (only if content was modified)
            if input_check.filtered_content != user_message:
                for msg in context.modified_request.messages:
                    if msg.role == "user" and msg.content == user_message:
                        msg.content = input_check.filtered_content
                        break
                user_message = input_check.filtered_content

        # 1. Policy check (block dangerous content)
        policy_result = await self._policy.check(user_message, context)
        if policy_result.blocked:
            context.set_block(policy_result.reason)
            return context

        # 2. Transform input if policy says so
        if policy_result.transformed_input:
            # Apply sanitization to the request
            for msg in context.modified_request.messages:
                if msg.role == "user" and msg.content == user_message:
                    msg.content = policy_result.transformed_input
                    break

        # 3. Bypass check (can we respond without LLM?)
        # Apply dynamic threshold from NEMOS if available
        original_threshold = self._classifier._settings.bypass_threshold
        effective_threshold = await self._resolve_dynamic_threshold(context, original_threshold)
        if effective_threshold != original_threshold:
            self._classifier._settings.bypass_threshold = effective_threshold

        bypass_result = await self._bypass.check(user_message, context)

        # Restore original threshold
        if effective_threshold != original_threshold:
            self._classifier._settings.bypass_threshold = original_threshold

        if bypass_result.should_bypass:
            context.set_bypass(bypass_result.response)
            context.metadata["detected_intent"] = bypass_result.intent
            context.metadata["intent_confidence"] = bypass_result.confidence
            return context

        return context

    @staticmethod
    async def _resolve_dynamic_threshold(context: PipelineContext, default: float) -> float:
        """Adjust bypass threshold based on IntentMemory from NEMOS.

        - High bypass success → relax threshold (±0.05, min 0.70)
        - Low bypass success → tighten threshold (±0.05, max 0.95)
        - No NEMOS data → return default unchanged
        """
        try:
            from aion.nemos import get_nemos
            intent_mem = await get_nemos().get_intent_memory(context.tenant)
        except Exception:
            return default

        if not intent_mem:
            return default

        # Check overall bypass effectiveness across all intents
        total_seen = sum(m.total_seen for m in intent_mem.values())
        if total_seen < 20:
            return default  # not enough data

        total_bypass = sum(m.bypassed_count for m in intent_mem.values())
        if total_bypass == 0:
            return default

        # Weighted average bypass success rate across intents
        weighted_success = sum(
            m.bypass_success_rate.value * m.bypassed_count
            for m in intent_mem.values() if m.bypassed_count > 0
        )
        avg_success = weighted_success / total_bypass

        if avg_success > 0.95:
            # Bypass working well → relax slightly
            return max(0.70, default - 0.05)
        elif avg_success < 0.85:
            # Bypass failing → tighten
            return min(0.95, default + 0.05)

        return default

    @staticmethod
    def _resolve_pii_policy(context: PipelineContext) -> PiiPolicyConfig | None:
        """Resolve PII policy from context metadata (set by middleware/overrides).

        Precedence: request > override > tenant > default (None = mask all).
        """
        raw = context.metadata.get("pii_policy")
        if raw is None:
            return None
        if isinstance(raw, PiiPolicyConfig):
            return raw
        if isinstance(raw, dict):
            return PiiPolicyConfig(**raw)
        return None


_instance = None


def get_module() -> EstixeModule:
    global _instance
    if _instance is None:
        _instance = EstixeModule()
    return _instance
