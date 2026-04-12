"""Policy engine — block, allow, transform rules applied in real-time.

Policies are loaded from YAML and can be updated via API without restart.
Includes automatic rollback if reload fails.
Validates regex patterns at load time to prevent DoS.
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

_MAX_PATTERN_LENGTH = 200


@dataclass
class PolicyResult:
    blocked: bool = False
    reason: str = ""
    transformed_input: Optional[str] = None
    matched_rules: list[str] = field(default_factory=list)


@dataclass
class PolicyRule:
    name: str
    action: str  # block | transform | flag
    pattern: Optional[str] = None
    compiled_pattern: Optional[re.Pattern] = field(default=None, repr=False)
    keywords: list[str] = field(default_factory=list)
    replacement: str = ""
    reason: str = ""


class PolicyEngine:
    """Evaluates request content against configurable policy rules."""

    def __init__(self) -> None:
        self._rules: list[PolicyRule] = []
        self._previous_rules: list[PolicyRule] = []  # for rollback
        from aion.config import _PROJECT_DIR
        self._config_path = _PROJECT_DIR / "config" / "policies.yaml"

    async def load(self, config_path: Optional[Path] = None) -> None:
        path = config_path or self._config_path
        if not path.exists():
            logger.info("No policy config found at %s — running without policies", path)
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        version = data.get("version", "unknown")
        logger.info("Loading policies version %s", version)

        new_rules = []
        for rule_data in data.get("policies", []):
            pattern = rule_data.get("pattern")
            compiled = None

            # Validate regex at load time (prevent DoS)
            if pattern:
                if len(pattern) > _MAX_PATTERN_LENGTH:
                    logger.warning("Pattern too long in rule '%s' (%d chars), skipping", rule_data.get("name"), len(pattern))
                    continue
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    logger.warning("Invalid regex in rule '%s': %s", rule_data.get("name"), e)
                    continue

            rule = PolicyRule(
                name=rule_data.get("name", "unnamed"),
                action=rule_data.get("action", "flag"),
                pattern=pattern,
                compiled_pattern=compiled,
                keywords=rule_data.get("keywords", []),
                replacement=rule_data.get("replacement", ""),
                reason=rule_data.get("reason", "Policy violation"),
            )
            new_rules.append(rule)

        self._rules = new_rules
        logger.info("Loaded %d policy rules (version %s)", len(self._rules), version)

    async def check(self, user_message: str, context: PipelineContext) -> PolicyResult:
        result = PolicyResult()
        message_lower = user_message.lower()

        for rule in self._rules:
            matched = False

            if rule.compiled_pattern:
                if rule.compiled_pattern.search(user_message):
                    matched = True
            elif rule.pattern:
                # Fallback for patterns added at runtime without pre-compilation
                try:
                    if re.search(rule.pattern, user_message, re.IGNORECASE):
                        matched = True
                except re.error:
                    pass

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
                return result

            elif rule.action == "transform":
                if rule.compiled_pattern and rule.replacement is not None:
                    transformed = rule.compiled_pattern.sub(rule.replacement, user_message)
                    result.transformed_input = transformed
                elif rule.pattern and rule.replacement is not None:
                    transformed = re.sub(rule.pattern, rule.replacement, user_message, flags=re.IGNORECASE)
                    result.transformed_input = transformed

            elif rule.action == "flag":
                context.metadata.setdefault("policy_flags", []).append(rule.name)

        return result

    async def reload(self, config_path: Optional[Path] = None) -> None:
        """Reload with automatic rollback on failure."""
        self._previous_rules = list(self._rules)
        try:
            await self.load(config_path)
            logger.info("Policy reload successful")
        except Exception:
            logger.exception("Policy reload FAILED — rolling back to previous state")
            self._rules = self._previous_rules
            raise

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    @property
    def rule_count(self) -> int:
        return len(self._rules)
