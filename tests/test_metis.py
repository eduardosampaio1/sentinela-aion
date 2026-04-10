"""Tests for METIS — Optimization Engine."""

import pytest

from aion.metis.compressor import PromptCompressor
from aion.metis.behavior import BehaviorConfig, BehaviorDial
from aion.metis.optimizer import ResponseOptimizer
from aion.config import MetisSettings
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
)


# --- Compressor tests ---

class TestPromptCompressor:
    def setup_method(self):
        self.compressor = PromptCompressor(MetisSettings())

    def test_clean_whitespace(self):
        req = ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role="user", content="hello    world\n\n\n\ntest")],
        )
        result = self.compressor.compress(req)
        assert "    " not in result.messages[0].content
        assert "\n\n\n\n" not in result.messages[0].content

    def test_dedup_system_messages(self):
        req = ChatCompletionRequest(
            model="test",
            messages=[
                ChatMessage(role="system", content="You are a helpful assistant."),
                ChatMessage(role="system", content="You are a helpful assistant.\nBe concise."),
                ChatMessage(role="user", content="hi"),
            ],
        )
        result = self.compressor.compress(req)
        system_msgs = [m for m in result.messages if m.role == "system"]
        assert len(system_msgs) == 1
        assert "helpful assistant" in system_msgs[0].content
        assert "concise" in system_msgs[0].content

    def test_trim_history(self):
        settings = MetisSettings(max_history_turns=2)
        compressor = PromptCompressor(settings)

        messages = [ChatMessage(role="system", content="System")]
        for i in range(10):
            messages.append(ChatMessage(role="user", content=f"Question {i}"))
            messages.append(ChatMessage(role="assistant", content=f"Answer {i}"))

        req = ChatCompletionRequest(model="test", messages=messages)
        result = compressor.compress(req)

        # Should keep system + last 4 messages (2 turns)
        assert len(result.messages) == 5  # 1 system + 4 conv
        assert result.messages[-1].content == "Answer 9"

    def test_count_tokens(self):
        req = ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role="user", content="Hello world")],
        )
        tokens = self.compressor.count_tokens(req)
        assert tokens > 0

    def test_disabled_compression(self):
        settings = MetisSettings(compression_enabled=False)
        compressor = PromptCompressor(settings)
        req = ChatCompletionRequest(
            model="test",
            messages=[
                ChatMessage(role="system", content="System"),
                ChatMessage(role="system", content="System"),
                ChatMessage(role="user", content="hi"),
            ],
        )
        result = compressor.compress(req)
        # Should not change anything
        assert len(result.messages) == 3


# --- Behavior Dial tests ---

class TestBehaviorDial:
    @pytest.fixture(autouse=True)
    def clear_store(self):
        from aion.metis.behavior import _behavior_store
        _behavior_store.clear()
        yield
        _behavior_store.clear()

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=90, density=80)
        await dial.set(config, "test-tenant")

        result = await dial.get("test-tenant")
        assert result is not None
        assert result.objectivity == 90
        assert result.density == 80

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        dial = BehaviorDial()
        result = await dial.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        dial = BehaviorDial()
        await dial.set(BehaviorConfig(), "tenant-1")
        await dial.delete("tenant-1")
        result = await dial.get("tenant-1")
        assert result is None

    def test_apply_high_objectivity(self):
        dial = BehaviorDial()
        config = BehaviorConfig(objectivity=90)
        req = ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role="user", content="hi")],
        )
        result = dial.apply_to_request(req, config)
        # Should have injected a system message
        system_msgs = [m for m in result.messages if m.role == "system"]
        assert len(system_msgs) == 1
        assert "concise" in system_msgs[0].content.lower()

    def test_apply_low_cost(self):
        dial = BehaviorDial()
        config = BehaviorConfig(cost_target="low")
        req = ChatCompletionRequest(
            model="test",
            messages=[
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="hi"),
            ],
        )
        result = dial.apply_to_request(req, config)
        system_content = result.messages[0].content
        assert "100 words" in system_content

    def test_no_instructions_for_default(self):
        dial = BehaviorDial()
        config = BehaviorConfig()  # all defaults (50)
        req = ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role="user", content="hi")],
        )
        result = dial.apply_to_request(req, config)
        # Default values should not inject instructions
        system_msgs = [m for m in result.messages if m.role == "system"]
        assert len(system_msgs) == 0


# --- Response Optimizer tests ---

class TestResponseOptimizer:
    def setup_method(self):
        self.optimizer = ResponseOptimizer()

    def _make_response(self, content: str) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            model="test",
            choices=[ChatCompletionChoice(
                message=ChatMessage(role="assistant", content=content),
            )],
        )

    def test_remove_filler_high_objectivity(self):
        config = BehaviorConfig(objectivity=80)
        response = self._make_response(
            "Certainly! I'd be happy to help. The answer is 42. "
            "I hope this helps! Let me know if you have any questions."
        )
        result = self.optimizer.optimize(response, config)
        content = result.choices[0].message.content
        assert "Certainly" not in content
        assert "happy to help" not in content
        assert "42" in content

    def test_no_change_low_objectivity(self):
        config = BehaviorConfig(objectivity=30)
        response = self._make_response("Certainly! The answer is 42.")
        result = self.optimizer.optimize(response, config)
        content = result.choices[0].message.content
        assert "Certainly" in content  # should NOT be removed

    def test_increase_density(self):
        config = BehaviorConfig(density=80)
        response = self._make_response("Line 1\n\n\n\n\nLine 2")
        result = self.optimizer.optimize(response, config)
        content = result.choices[0].message.content
        assert "\n\n\n" not in content

    def test_empty_response(self):
        config = BehaviorConfig(objectivity=90)
        response = self._make_response("")
        result = self.optimizer.optimize(response, config)
        assert result.choices[0].message.content == ""
