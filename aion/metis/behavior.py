"""Behavior Dial — parametric control of AI behavior in real-time.

Dimensions:
- objectivity: 0 (consultive) to 100 (minimal)
- density: 0 (detailed) to 100 (telegraphic)
- explanation: 0 (didactic) to 100 (no explanation)
- cost_target: "free" | "low" | "medium" | "high"
- formality: 0 (formal) to 100 (casual)
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from aion.shared.schemas import ChatCompletionRequest, ChatMessage

logger = logging.getLogger("aion.metis.behavior")

# In-memory behavior storage per tenant (Redis in production)
_behavior_store: dict[str, "BehaviorConfig"] = {}


class BehaviorConfig(BaseModel):
    """Behavior dial settings."""
    objectivity: int = Field(default=50, ge=0, le=100)
    density: int = Field(default=50, ge=0, le=100)
    explanation: int = Field(default=50, ge=0, le=100)
    cost_target: str = Field(default="medium")  # free | low | medium | high
    formality: int = Field(default=50, ge=0, le=100)


class BehaviorDial:
    """Manages behavior settings per tenant and translates them to system instructions."""

    async def get(self, tenant: str = "default") -> Optional[BehaviorConfig]:
        """Get behavior config for tenant."""
        return _behavior_store.get(tenant)

    async def set(self, config: BehaviorConfig, tenant: str = "default") -> None:
        """Set behavior config for tenant. Takes effect immediately."""
        _behavior_store[tenant] = config
        logger.info("Behavior updated for tenant '%s': %s", tenant, config.model_dump())

    async def delete(self, tenant: str = "default") -> None:
        """Remove behavior config for tenant."""
        _behavior_store.pop(tenant, None)

    def apply_to_request(
        self, request: ChatCompletionRequest, config: BehaviorConfig
    ) -> ChatCompletionRequest:
        """Inject behavior instructions into the system prompt."""
        instructions = self._build_instructions(config)
        if not instructions:
            return request

        modified = request.model_copy(deep=True)

        # Find or create system message
        system_found = False
        for msg in modified.messages:
            if msg.role == "system":
                msg.content = (msg.content or "") + "\n\n" + instructions
                system_found = True
                break

        if not system_found:
            modified.messages.insert(
                0, ChatMessage(role="system", content=instructions)
            )

        return modified

    @staticmethod
    def _build_instructions(config: BehaviorConfig) -> str:
        """Translate behavior config into natural language instructions."""
        parts = []

        # Objectivity
        if config.objectivity >= 80:
            parts.append(
                "Be extremely concise and direct. No filler words, no pleasantries, "
                "no unnecessary context. Answer in the minimum number of words possible."
            )
        elif config.objectivity >= 60:
            parts.append(
                "Be direct and objective. Avoid unnecessary elaboration."
            )
        elif config.objectivity <= 20:
            parts.append(
                "Be thorough and consultative. Explain your reasoning and provide context."
            )

        # Density
        if config.density >= 80:
            parts.append("Use telegraphic style. Bullet points preferred over paragraphs.")
        elif config.density >= 60:
            parts.append("Keep responses compact. Prefer short paragraphs.")

        # Explanation
        if config.explanation >= 80:
            parts.append("Do not explain your reasoning. Just give the answer.")
        elif config.explanation <= 20:
            parts.append("Explain your reasoning step by step.")

        # Formality
        if config.formality >= 80:
            parts.append("Use casual, informal language.")
        elif config.formality <= 20:
            parts.append("Use formal, professional language.")

        # Cost target
        if config.cost_target == "low":
            parts.append("Keep your response under 100 words.")
        elif config.cost_target == "free":
            parts.append("Keep your response under 50 words. Be as brief as possible.")

        if not parts:
            return ""

        return "BEHAVIOR INSTRUCTIONS:\n" + "\n".join(f"- {p}" for p in parts)
