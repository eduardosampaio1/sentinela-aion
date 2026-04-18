"""Tests for Behavior Dial parameter mapping (hard guarantees)."""

import pytest

from aion.metis.behavior import BehaviorConfig, BehaviorDial
from aion.shared.schemas import ChatCompletionRequest, ChatMessage


def _make_request(
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="test")],
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
    )


class TestParameterMapping:
    def test_high_objectivity_caps_temperature(self):
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=80)
        req = _make_request(temperature=0.9)
        result = dial.apply_to_request(req, config)
        assert result.temperature == 0.3  # capped

    def test_high_objectivity_caps_top_p(self):
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=80)
        req = _make_request(top_p=0.95)
        result = dial.apply_to_request(req, config)
        assert result.top_p == 0.8

    def test_high_objectivity_preserves_lower_temperature(self):
        """If user set temperature=0.1, don't raise it."""
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=80)
        req = _make_request(temperature=0.1)
        result = dial.apply_to_request(req, config)
        assert result.temperature == 0.1  # preserved (already below cap)

    def test_medium_objectivity_caps_at_06(self):
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=65)
        req = _make_request(temperature=0.9)
        result = dial.apply_to_request(req, config)
        assert result.temperature == 0.6

    def test_high_density_caps_max_tokens(self):
        dial = BehaviorDial()
        config = BehaviorConfig(density=80)
        req = _make_request(max_tokens=2000)
        result = dial.apply_to_request(req, config)
        assert result.max_tokens == 500

    def test_cost_free_forces_deterministic(self):
        dial = BehaviorDial()
        config = BehaviorConfig(cost_target="free")
        req = _make_request(temperature=0.7, max_tokens=4096)
        result = dial.apply_to_request(req, config)
        assert result.temperature == 0.0
        assert result.max_tokens == 100

    def test_cost_low_caps_max_tokens(self):
        dial = BehaviorDial()
        config = BehaviorConfig(cost_target="low")
        req = _make_request(max_tokens=4096)
        result = dial.apply_to_request(req, config)
        assert result.max_tokens == 300

    def test_default_config_changes_nothing(self):
        dial = BehaviorDial()
        config = BehaviorConfig()  # all defaults (50, medium)
        req = _make_request(temperature=0.7, top_p=0.9, max_tokens=2000)
        result = dial.apply_to_request(req, config)
        assert result.temperature == 0.7
        assert result.top_p == 0.9
        assert result.max_tokens == 2000

    def test_none_params_get_set_when_needed(self):
        """When user didn't set temperature, behavior dial can set it."""
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=80)
        req = _make_request()  # temperature=None
        result = dial.apply_to_request(req, config)
        assert result.temperature == 0.3  # set by dial

    def test_prompt_instructions_still_injected(self):
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=80)
        req = _make_request()
        result = dial.apply_to_request(req, config)
        # Both layers applied
        assert result.temperature == 0.3  # parameter
        system_msg = next(m for m in result.messages if m.role == "system")
        assert "BEHAVIOR INSTRUCTIONS" in system_msg.content  # prompt
