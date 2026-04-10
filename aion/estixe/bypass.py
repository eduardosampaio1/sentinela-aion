"""Bypass engine — Zero-Token Response Engine.

Responds directly when the classifier identifies a known intent,
avoiding unnecessary LLM calls.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from aion.estixe.classifier import SemanticClassifier
from aion.shared.schemas import (
    ChatCompletionChoice,
    ChatCompletionResponse,
    ChatMessage,
    PipelineContext,
    UsageInfo,
)

logger = logging.getLogger("aion.estixe.bypass")


@dataclass
class BypassResult:
    """Result of a bypass check."""
    should_bypass: bool
    response: Optional[ChatCompletionResponse] = None
    intent: str = ""
    confidence: float = 0.0


class BypassEngine:
    """Checks if a request can be answered without calling the LLM."""

    def __init__(self, classifier: SemanticClassifier) -> None:
        self._classifier = classifier

    async def check(self, user_message: str, context: PipelineContext) -> BypassResult:
        """Check if the user message can be bypassed."""
        match = self._classifier.classify(user_message)

        if match is None:
            return BypassResult(should_bypass=False)

        if match.action != "bypass":
            # Intent recognized but action is passthrough — don't bypass
            context.metadata["detected_intent"] = match.intent
            context.metadata["intent_confidence"] = match.confidence
            return BypassResult(should_bypass=False, intent=match.intent)

        if not match.response_templates:
            logger.warning(
                "Intent '%s' matched but has no response templates", match.intent
            )
            return BypassResult(should_bypass=False)

        # Build bypass response
        response_text = random.choice(match.response_templates)
        response = self._build_response(response_text, context)

        logger.info(
            "BYPASS: intent='%s' confidence=%.3f input='%s'",
            match.intent,
            match.confidence,
            user_message[:80],
        )

        return BypassResult(
            should_bypass=True,
            response=response,
            intent=match.intent,
            confidence=match.confidence,
        )

    @staticmethod
    def _build_response(
        text: str, context: PipelineContext
    ) -> ChatCompletionResponse:
        """Build an OpenAI-compatible response for a bypass."""
        return ChatCompletionResponse(
            model="aion-bypass",
            created=int(time.time()),
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=text),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
        )
