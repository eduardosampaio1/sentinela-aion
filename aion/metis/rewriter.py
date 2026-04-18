"""Prompt Rewriter — lightweight rule-based prompt enhancement.

Golden rule: AION melhora, nunca muda intencao.
- Only APPENDS to the user message (never edits or removes)
- Rules are configurable YAML
- Audit: before/after always logged
- If a rule worsens quality (NEMOS feedback), ActuationGuard disables it
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from aion.shared.schemas import ChatCompletionRequest
from aion.shared.tokens import extract_user_message

logger = logging.getLogger("aion.metis.rewriter")


@dataclass
class RewriteRule:
    """A single rewrite rule from config."""
    match_pattern: Optional[str] = None  # regex (case-insensitive)
    match_intent: Optional[str] = None   # ESTIXE intent name
    suffix: str = ""
    condition: str = "short"  # short (<50w) | medium (<100w) | any
    level: str = "light"      # light | moderate


@dataclass
class RewriteResult:
    """Result of rewrite attempt."""
    applied: bool = False
    rule_name: str = ""
    suffix: str = ""
    original_length: int = 0
    rewritten_length: int = 0


class PromptRewriter:
    """Enhances vague prompts by appending specificity. Never changes meaning."""

    def __init__(self) -> None:
        self._rules: list[RewriteRule] = []
        self._loaded = False
        self._disabled_rules: set[str] = set()  # rules disabled by ActuationGuard

    async def load(self, config_dir: Optional[Path] = None) -> None:
        """Load rewrite rules from YAML config."""
        if config_dir is None:
            from aion.config import get_settings
            config_dir = get_settings().config_dir

        path = config_dir / "rewrite_rules.yaml"
        if not path.exists():
            logger.debug("No rewrite rules file: %s", path)
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._rules = []
        for rule_data in data.get("rules", []):
            self._rules.append(RewriteRule(
                match_pattern=rule_data.get("match_pattern"),
                match_intent=rule_data.get("match_intent"),
                suffix=rule_data.get("suffix", ""),
                condition=rule_data.get("condition", "short"),
                level=rule_data.get("level", "light"),
            ))

        self._loaded = True
        logger.info("Loaded %d rewrite rules", len(self._rules))

    def rewrite(
        self,
        request: ChatCompletionRequest,
        *,
        rewrite_level: str = "light",
        detected_intent: str = "",
    ) -> tuple[ChatCompletionRequest, RewriteResult]:
        """Apply the first matching rewrite rule. Returns (modified_request, result).

        Level hierarchy: off < light < moderate
        A rule with level="moderate" only fires if rewrite_level >= "moderate".
        """
        result = RewriteResult()

        if rewrite_level == "off" or not self._rules:
            return request, result

        user_message = extract_user_message(request)
        if not user_message:
            return request, result

        result.original_length = len(user_message)
        word_count = len(user_message.split())

        for rule in self._rules:
            rule_id = rule.match_pattern or rule.match_intent or "unknown"

            # Skip disabled rules
            if rule_id in self._disabled_rules:
                continue

            # Level check
            if rule.level == "moderate" and rewrite_level == "light":
                continue

            # Condition check
            if rule.condition == "short" and word_count >= 50:
                continue
            if rule.condition == "medium" and word_count >= 100:
                continue

            # Match check
            matched = False
            if rule.match_pattern:
                if re.search(rule.match_pattern, user_message, re.IGNORECASE):
                    matched = True
            if rule.match_intent and detected_intent:
                if rule.match_intent.lower() in detected_intent.lower():
                    matched = True

            if not matched:
                continue

            # Apply: append suffix to the last user message
            modified = request.model_copy(deep=True)
            for msg in reversed(modified.messages):
                if msg.role == "user" and msg.content:
                    msg.content = msg.content.rstrip() + "\n\n" + rule.suffix
                    break

            result.applied = True
            result.rule_name = rule_id
            result.suffix = rule.suffix
            result.rewritten_length = len(msg.content)

            logger.debug(
                '{"event":"rewrite_applied","rule":"%s","original_len":%d,"new_len":%d}',
                rule_id, result.original_length, result.rewritten_length,
            )

            return modified, result

        return request, result

    def disable_rule(self, rule_id: str) -> None:
        """Disable a rule (called by ActuationGuard when quality drops)."""
        self._disabled_rules.add(rule_id)
        logger.warning('{"event":"rewrite_rule_disabled","rule":"%s"}', rule_id)

    def enable_rule(self, rule_id: str) -> None:
        """Re-enable a previously disabled rule."""
        self._disabled_rules.discard(rule_id)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    @property
    def active_rule_count(self) -> int:
        return len(self._rules) - len(self._disabled_rules)
