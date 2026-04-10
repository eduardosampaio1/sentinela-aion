"""Tests for NOMOS — Decision Engine."""

import os
from unittest.mock import patch

import pytest

from aion.nomos.classifier import ComplexityClassifier
from aion.nomos.registry import ModelConfig, ModelRegistry
from aion.nomos.router import Router
from aion.nomos.cost import estimate_prompt_tokens, estimate_request_cost, estimate_savings
from aion.config import NomosSettings
from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext


# --- Classifier tests ---

class TestComplexityClassifier:
    def setup_method(self):
        self.classifier = ComplexityClassifier()

    def test_simple_greeting(self):
        result = self.classifier.classify([{"role": "user", "content": "oi"}])
        assert result.score < 30

    def test_simple_question(self):
        result = self.classifier.classify([{"role": "user", "content": "What is Python?"}])
        assert result.score < 40

    def test_complex_code_request(self):
        result = self.classifier.classify([{
            "role": "user",
            "content": (
                "Please implement a function that takes a list of integers "
                "and returns the longest increasing subsequence. Write the code "
                "step by step with explanation and optimize for performance."
            ),
        }])
        assert result.score > 30

    def test_very_complex_with_code_block(self):
        result = self.classifier.classify([{
            "role": "user",
            "content": (
                "Analyze this code and explain why it fails:\n"
                "```python\n"
                "async def process(data):\n"
                "    result = await compute(data)\n"
                "    return result\n"
                "```\n"
                "Compare it with an alternative approach and evaluate "
                "which is better for our use case."
            ),
        }])
        assert result.score > 40

    def test_long_conversation_adds_complexity(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ] * 6  # 12 messages
        messages.append({"role": "user", "content": "ok"})
        result = self.classifier.classify(messages)
        assert "long_conversation" in str(result.factors)

    def test_empty_messages(self):
        result = self.classifier.classify([])
        assert result.score == 0

    def test_score_clamped_to_100(self):
        # Very complex prompt
        result = self.classifier.classify([{
            "role": "user",
            "content": (
                "Explain step by step how to implement, analyze, compare, evaluate, "
                "and optimize a complex algorithm. Write code, create a table, "
                "generate JSON output, calculate the complexity, and solve the proof. "
                "Additionally, furthermore, moreover, also translate it. "
                "```python\ndef foo(): pass\n```"
            ),
        }])
        assert result.score <= 100


# --- Registry tests ---

class TestModelRegistry:
    @pytest.fixture
    def models_yaml(self, tmp_path):
        content = """
models:
  - name: cheap-model
    provider: openai
    api_key_env: OPENAI_API_KEY
    cost_per_1k_input: 0.0001
    cost_per_1k_output: 0.0004
    max_tokens: 8192
    latency_p50_ms: 200
    capabilities: [fast, cheap]
    complexity_range: [0, 40]

  - name: premium-model
    provider: anthropic
    api_key_env: ANTHROPIC_API_KEY
    cost_per_1k_input: 0.003
    cost_per_1k_output: 0.015
    max_tokens: 200000
    latency_p50_ms: 1000
    capabilities: [premium, reasoning]
    complexity_range: [50, 100]
"""
        path = tmp_path / "models.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    @pytest.mark.asyncio
    async def test_load_models(self, models_yaml):
        settings = NomosSettings(models_config_path=models_yaml)
        registry = ModelRegistry(settings)
        await registry.load()
        assert registry.model_count == 2

    @pytest.mark.asyncio
    async def test_get_available_models(self, models_yaml):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": ""}):
            settings = NomosSettings(models_config_path=models_yaml)
            registry = ModelRegistry(settings)
            await registry.load()
            available = registry.get_available_models()
            assert len(available) == 1
            assert available[0].name == "cheap-model"

    @pytest.mark.asyncio
    async def test_get_models_for_complexity(self, models_yaml):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant-test"}):
            settings = NomosSettings(models_config_path=models_yaml)
            registry = ModelRegistry(settings)
            await registry.load()

            simple = registry.get_models_for_complexity(20)
            assert any(m.name == "cheap-model" for m in simple)

            complex_ = registry.get_models_for_complexity(80)
            assert any(m.name == "premium-model" for m in complex_)

    @pytest.mark.asyncio
    async def test_get_cheapest(self, models_yaml):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant-test"}):
            settings = NomosSettings(models_config_path=models_yaml)
            registry = ModelRegistry(settings)
            await registry.load()
            cheapest = registry.get_cheapest()
            assert cheapest.name == "cheap-model"


# --- Router tests ---

class TestRouter:
    @pytest.fixture
    def registry_with_models(self):
        registry = ModelRegistry(NomosSettings())
        registry._models = [
            ModelConfig(
                name="light",
                provider="openai",
                api_key_env="OPENAI_API_KEY",
                cost_per_1k_input=0.0001,
                cost_per_1k_output=0.0004,
                complexity_range=(0, 40),
                latency_p50_ms=200,
            ),
            ModelConfig(
                name="heavy",
                provider="anthropic",
                api_key_env="ANTHROPIC_API_KEY",
                cost_per_1k_input=0.003,
                cost_per_1k_output=0.015,
                complexity_range=(40, 100),
                latency_p50_ms=1000,
            ),
        ]
        return registry

    def test_simple_prompt_routes_to_light(self, registry_with_models):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant-test"}):
            router = Router(registry_with_models, ComplexityClassifier())
            request = ChatCompletionRequest(
                model="any",
                messages=[ChatMessage(role="user", content="What is 2+2?")],
            )
            result = router.route(request, PipelineContext())
            assert result.model_name == "light"

    def test_complex_prompt_routes_to_heavy(self, registry_with_models):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant-test"}):
            router = Router(registry_with_models, ComplexityClassifier())
            request = ChatCompletionRequest(
                model="any",
                messages=[ChatMessage(
                    role="user",
                    content=(
                        "Please implement step by step a complex algorithm "
                        "that analyzes and compares multiple data structures. "
                        "Write code with explanation, evaluate performance, "
                        "and create a JSON output format. "
                        "```python\ndef analyze(): pass\n```"
                    ),
                )],
            )
            result = router.route(request, PipelineContext())
            assert result.model_name == "heavy"

    def test_no_models_uses_request_model(self):
        registry = ModelRegistry(NomosSettings())
        registry._models = []
        router = Router(registry, ComplexityClassifier())
        request = ChatCompletionRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="hi")],
        )
        result = router.route(request, PipelineContext())
        assert result.model_name == "gpt-4o"
        assert "fallback" in result.reason

    def test_cost_target_low(self, registry_with_models):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-ant-test"}):
            router = Router(registry_with_models, ComplexityClassifier())
            request = ChatCompletionRequest(
                model="any",
                messages=[ChatMessage(
                    role="user",
                    content="Analyze this complex code step by step and evaluate it",
                )],
            )
            ctx = PipelineContext()
            ctx.metadata["cost_target"] = "low"
            result = router.route(request, ctx)
            assert result.model_name == "light"  # cost_target overrides complexity


# --- Cost tests ---

class TestCost:
    def test_estimate_tokens(self):
        tokens = estimate_prompt_tokens("Hello world this is a test")
        assert tokens > 0

    def test_estimate_request_cost(self):
        model = ModelConfig(
            name="test",
            provider="openai",
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
        )
        cost = estimate_request_cost(model, prompt_tokens=1000, completion_tokens=500)
        assert cost == 0.001 + 0.001  # 1.0 + 1.0

    def test_estimate_savings(self):
        expensive = ModelConfig(
            name="expensive",
            provider="openai",
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
        )
        cheap = ModelConfig(
            name="cheap",
            provider="openai",
            cost_per_1k_input=0.0001,
            cost_per_1k_output=0.0004,
        )
        savings = estimate_savings(expensive, cheap, prompt_tokens=500, completion_tokens=200)
        assert savings > 0
