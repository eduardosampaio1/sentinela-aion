"""Tests for NOMOS multi-factor routing intelligence.

Covers: risk-aware scoring, capability matching, score breakdown,
PII-influenced routing, configurable weights, backward compat.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from aion.config import NomosSettings, ScoringWeights
from aion.nomos.classifier import ComplexityClassifier
from aion.nomos.registry import ModelConfig, ModelRegistry
from aion.nomos.router import Router, ScoreBreakdown
from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext


# ── Helpers ──

def _model(
    name: str,
    cost_input: float = 0.001,
    cost_output: float = 0.002,
    latency: int = 500,
    complexity: tuple = (0, 100),
    capabilities: list | None = None,
    risk_tier: str = "medium",
) -> ModelConfig:
    return ModelConfig(
        name=name,
        provider="openai",
        api_key_env="OPENAI_API_KEY",
        cost_per_1k_input=cost_input,
        cost_per_1k_output=cost_output,
        latency_p50_ms=latency,
        complexity_range=complexity,
        capabilities=capabilities or [],
        risk_tier=risk_tier,
    )


def _request(msg: str = "Hello") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content=msg)],
    )


def _context(**meta) -> PipelineContext:
    ctx = PipelineContext(tenant="test")
    ctx.metadata.update(meta)
    return ctx


@pytest.fixture(autouse=True)
def _set_api_key():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        yield


@pytest.fixture
def weights():
    return ScoringWeights()


# ── ScoreBreakdown ──

def test_score_breakdown_to_dict():
    s = ScoreBreakdown(cost=1.0, fit=2.0, latency=3.0, risk=4.0, capability=5.0, total=15.0)
    d = s.to_dict()
    assert d == {"cost": 1.0, "fit": 2.0, "latency": 3.0, "risk": 4.0, "capability": 5.0, "total": 15.0}


# ── Multi-factor scoring ──

def test_pii_penalizes_low_risk_model():
    """When PII is detected, low-tier models get a penalty."""
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [
        _model("cheap", cost_input=0.0001, cost_output=0.0004, risk_tier="low"),
        _model("safe", cost_input=0.003, cost_output=0.015, risk_tier="high"),
    ]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    # Without PII — cheap model wins
    ctx_no_pii = _context()
    route_no_pii = router.route(_request(), ctx_no_pii)
    assert route_no_pii.model_name == "cheap"
    assert not route_no_pii.pii_influenced

    # With PII — safe model should win (penalty pushes cheap out)
    ctx_pii = _context(pii_violations=["pii:cpf"])
    route_pii = router.route(_request(), ctx_pii)
    assert route_pii.model_name == "safe"
    assert route_pii.pii_influenced


def test_pii_does_not_affect_high_tier_models():
    """High-risk-tier models are not penalized when PII is present."""
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [
        _model("premium-a", cost_input=0.003, cost_output=0.015, risk_tier="high"),
        _model("premium-b", cost_input=0.004, cost_output=0.016, risk_tier="high"),
    ]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    ctx_pii = _context(pii_violations=["pii:email"])
    route = router.route(_request(), ctx_pii)
    # Should pick the cheaper high-tier model (no risk penalty)
    assert route.model_name == "premium-a"
    assert not route.pii_influenced  # both are high tier, no influence


def test_capability_miss_penalizes():
    """Models missing required capabilities get penalized."""
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [
        _model("cheap", cost_input=0.0001, capabilities=["fast", "cheap"]),
        _model("coder", cost_input=0.003, capabilities=["code", "reasoning"]),
    ]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    ctx = _context(required_capabilities=["code"])
    route = router.route(_request(), ctx)
    assert route.model_name == "coder"


def test_no_required_capabilities_no_penalty():
    """Without required capabilities, no capability penalty."""
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [
        _model("cheap", cost_input=0.0001, capabilities=[]),
        _model("expensive", cost_input=0.01, capabilities=["everything"]),
    ]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    ctx = _context()
    route = router.route(_request(), ctx)
    assert route.model_name == "cheap"  # no capability requirement → cheapest wins


def test_score_breakdown_in_route_decision():
    """Route decision includes score breakdown."""
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [_model("m1"), _model("m2")]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    route = router.route(_request(), _context())
    assert route.score_breakdown is not None
    d = route.score_breakdown.to_dict()
    assert "cost" in d
    assert "fit" in d
    assert "latency" in d
    assert "risk" in d
    assert "capability" in d
    assert "total" in d


def test_candidates_evaluated_count():
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [_model("m1"), _model("m2"), _model("m3")]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    route = router.route(_request(), _context())
    assert route.candidates_evaluated == 3


def test_configurable_weights_change_result():
    """Different scoring weights can change the selected model."""
    # With high risk penalty
    settings_high_risk = NomosSettings(
        scoring_weights=ScoringWeights(risk_penalty=1000.0),
    )
    # With zero risk penalty
    settings_no_risk = NomosSettings(
        scoring_weights=ScoringWeights(risk_penalty=0.0),
    )

    models = [
        _model("cheap-risky", cost_input=0.0001, cost_output=0.0004, risk_tier="low"),
        _model("expensive-safe", cost_input=0.01, cost_output=0.02, risk_tier="high"),
    ]

    registry1 = ModelRegistry(settings_high_risk)
    registry1._models = list(models)
    router1 = Router(registry1, ComplexityClassifier(), settings_high_risk)

    registry2 = ModelRegistry(settings_no_risk)
    registry2._models = list(models)
    router2 = Router(registry2, ComplexityClassifier(), settings_no_risk)

    ctx = _context(pii_violations=["pii:cpf"])

    # High risk penalty → safe model wins
    assert router1.route(_request(), ctx).model_name == "expensive-safe"
    # No risk penalty → cheap model wins
    assert router2.route(_request(), ctx).model_name == "cheap-risky"


# ── Backward compat ──

def test_backward_compat_no_pii_no_caps():
    """Without PII or capability requirements, scoring is backward compatible."""
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [
        _model("cheap", cost_input=0.0001, cost_output=0.0004, latency=300),
        _model("expensive", cost_input=0.01, cost_output=0.02, latency=1000),
    ]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    ctx = _context()  # no PII, no capabilities
    route = router.route(_request(), ctx)
    # Cheap model should win (same as original simple scoring)
    assert route.model_name == "cheap"
    assert not route.pii_influenced


def test_cost_target_low_bypasses_scoring():
    """cost_target=low still bypasses multi-factor and picks cheapest."""
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [
        _model("cheap", cost_input=0.0001, cost_output=0.0004, risk_tier="low"),
        _model("safe", cost_input=0.01, cost_output=0.02, risk_tier="high"),
    ]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    # Even with PII, cost_target=low overrides
    ctx = _context(cost_target="low", pii_violations=["pii:cpf"])
    route = router.route(_request(), ctx)
    assert route.model_name == "cheap"
    assert route.score_breakdown is None  # bypassed scoring


def test_cost_target_fast_bypasses_scoring():
    settings = NomosSettings()
    registry = ModelRegistry(settings)
    registry._models = [
        _model("slow", latency=1000),
        _model("fast", latency=100),
    ]
    classifier = ComplexityClassifier()
    router = Router(registry, classifier, settings)

    ctx = _context(cost_target="fast")
    route = router.route(_request(), ctx)
    assert route.model_name == "fast"
