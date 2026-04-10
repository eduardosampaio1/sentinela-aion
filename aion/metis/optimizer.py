"""Response optimizer — adjusts LLM output based on behavior dial."""

from __future__ import annotations

import re

from aion.metis.behavior import BehaviorConfig
from aion.shared.schemas import ChatCompletionResponse


class ResponseOptimizer:
    """Optimizes LLM responses based on behavior settings."""

    def optimize(
        self, response: ChatCompletionResponse, config: BehaviorConfig
    ) -> ChatCompletionResponse:
        """Apply post-processing optimization to the response."""
        if not response.choices:
            return response

        content = response.choices[0].message.content
        if not content:
            return response

        # Apply optimizations based on behavior dial
        if config.objectivity >= 70:
            content = self._remove_filler(content)

        if config.density >= 70:
            content = self._increase_density(content)

        # Update response
        response.choices[0].message.content = content
        return response

    @staticmethod
    def _remove_filler(text: str) -> str:
        """Remove common filler phrases from LLM output."""
        filler_patterns = [
            r"^(Certainly!|Sure!|Of course!|Great question!|That's a great question!)\s*",
            r"^(I'd be happy to help[ .!]*)\s*",
            r"^(Let me explain[ .]*)\s*",
            r"^(Here's what I think:?\s*)",
            r"\b(basically|essentially|actually|literally|in fact)\b",
            r"(I hope this helps[.!]*)\s*$",
            r"(Let me know if you have any (?:other |more )?questions[.!]*)\s*$",
            r"(Feel free to ask if you need (?:anything|more help)[.!]*)\s*$",
            r"(Is there anything else (?:I can help with|you'd like to know)[?!]*)\s*$",
        ]
        result = text
        for pattern in filler_patterns:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE | re.MULTILINE)
        return result.strip()

    @staticmethod
    def _increase_density(text: str) -> str:
        """Make text more compact."""
        # Remove excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove trailing spaces
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()
