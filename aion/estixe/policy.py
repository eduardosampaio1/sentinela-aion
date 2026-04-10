"""Policy engine — block, allow, transform rules applied in real-time.

Policies are loaded from YAML and can be updated via API without restart.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from aion.shared.schemas import PipelineContext

logger = logging.getLogger("aion.estixe.policy")


@dataclass
class PolicyResult:
    """Result of a policy check."""
    blocked: bool = False
    reason: str = ""
    transformed_input: Optional[str] = None
    matched_rules: list[str] = field(default_factory=list)


@dataclass
class PolicyRule:
    """A single policy rule."""
    name: str
    action: str  # block | transform | flag
    pattern: Optional[str] = None  # regex pattern
    keywords: list[str] = field(default_factory=list)
    replacement: str = ""  # for transform action
    reason: str = ""


class PolicyEngine:
    """Evaluates request content against configurable policy rules."""

    def __init__(self) -> None:
        self._rules: list[PolicyRule] = []
        self._config_path = Path("config/policies.yaml")

    async def load(self, config_path: Optional[Path] = None) -> None:
        """Load policies from YAML config."""
        path = config_path or self._config_path
        if not path.exists():
            logger.info("No policy config found at %s — running without policies", path)
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._rules = []
        for rule_data in data.get("policies", []):
            rule = PolicyRule(
                name=rule_data.get("name", "unnamed"),
                action=rule_data.get("action", "flag"),
                pattern=rule_data.get("pattern"),
                keywords=rule_data.get("keywords", []),
                replacement=rule_data.get("replacement", ""),
                reason=rule_data.get("reason", "Policy violation"),
            )
            self._rules.append(rule)

        logger.info("Loaded %d policy rules", len(self._rules))

    async def check(self, user_message: str, context: PipelineContext) -> PolicyResult:
        """Check user message against all active policy rules."""
        result = PolicyResult()
        message_lower = user_message.lower()

        for rule in self._rules:
            matched = False

            # Check regex pattern
            if rule.pattern:
                try:
                    if re.search(rule.pattern, user_message, re.IGNORECASE):
                        matched = True
                except re.error:
                    logger.warning("Invalid regex in rule '%s': %s", rule.name, rule.pattern)

            # Check keywords
            if not matched and rule.keywords:
                for keyword in rule.keywords:
                    if keyword.lower() in message_lower:
                        matched = True
                        break

            if not matched:
                continue

            result.matched_rules.append(rule.name)

            if rule.action == "block":
                result.blocked = True
                result.reason = rule.reason or f"Blocked by policy: {rule.name}"
                logger.info("BLOCKED by policy '%s': %s", rule.name, result.reason)
                return result  # Block is final

            elif rule.action == "transform":
                if rule.pattern and rule.replacement is not None:
                    transformed = re.sub(
                        rule.pattern, rule.replacement, user_message, flags=re.IGNORECASE
                    )
                    result.transformed_input = transformed
                    logger.debug("TRANSFORM by policy '%s'", rule.name)

            elif rule.action == "flag":
                context.metadata.setdefault("policy_flags", []).append(rule.name)
                logger.debug("FLAGGED by policy '%s'", rule.name)

        return result

    async def reload(self, config_path: Optional[Path] = None) -> None:
        """Reload policies (hot-reload)."""
        await self.load(config_path)

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a rule at runtime (via API)."""
        self._rules.append(rule)
        logger.info("Added policy rule: %s", rule.name)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        removed = len(self._rules) < before
        if removed:
            logger.info("Removed policy rule: %s", name)
        return removed

    @property
    def rule_count(self) -> int:
        return len(self._rules)
