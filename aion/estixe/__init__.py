"""ESTIXE — Control & Bypass Engine. Bloqueia, bypassa, aplica politica, reduz risco."""

from __future__ import annotations

import logging

from aion.config import get_estixe_settings
from aion.estixe.bypass import BypassEngine
from aion.estixe.classifier import SemanticClassifier
from aion.estixe.policy import PolicyEngine
from aion.shared.schemas import ChatCompletionRequest, PipelineContext

logger = logging.getLogger("aion.estixe")


class EstixeModule:
    """ESTIXE pipeline module — runs classification, policy, and bypass."""

    name = "estixe"

    def __init__(self) -> None:
        settings = get_estixe_settings()
        self._classifier = SemanticClassifier(settings)
        self._bypass = BypassEngine(self._classifier)
        self._policy = PolicyEngine()
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

        # Extract user message (last user message in the conversation)
        user_message = self._extract_user_message(request)
        if not user_message:
            return context

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
        bypass_result = await self._bypass.check(user_message, context)
        if bypass_result.should_bypass:
            context.set_bypass(bypass_result.response)
            return context

        return context

    @staticmethod
    def _extract_user_message(request: ChatCompletionRequest) -> str | None:
        for msg in reversed(request.messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return None


_instance = None


def get_module() -> EstixeModule:
    global _instance
    if _instance is None:
        _instance = EstixeModule()
    return _instance
