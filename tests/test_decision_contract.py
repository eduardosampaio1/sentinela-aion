"""Tests for DecisionContract primitives and builder."""

from __future__ import annotations

import time

import pytest

from aion.contract import (
    Action,
    Capabilities,
    CapabilityState,
    ConfidenceLevel,
    ContractError,
    ContractMeta,
    ContractMetrics,
    DecisionConfidence,
    DecisionContract,
    ErrorType,
    ExtensionEntry,
    FinalOutput,
    RetryPolicy,
    SideEffectLevel,
    build_contract,
    default_retry_policy,
    side_effect_for,
    target_type_for,
)
from aion.shared.schemas import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Decision,
    PipelineContext,
)


# ── Action → side_effect / target_type mappings ──

class TestActionMappings:
    def test_call_llm_is_none_side_effect(self):
        assert side_effect_for(Action.CALL_LLM) == SideEffectLevel.NONE
        assert target_type_for(Action.CALL_LLM) == "llm"

    def test_call_service_is_external(self):
        assert side_effect_for(Action.CALL_SERVICE) == SideEffectLevel.EXTERNAL
        assert target_type_for(Action.CALL_SERVICE) == "service"

    def test_bypass_is_direct(self):
        assert target_type_for(Action.BYPASS) == "direct"
        assert side_effect_for(Action.BYPASS) == SideEffectLevel.NONE

    def test_block_is_direct(self):
        assert target_type_for(Action.BLOCK) == "direct"

    def test_approval_is_human(self):
        assert side_effect_for(Action.REQUEST_HUMAN_APPROVAL) == SideEffectLevel.HUMAN
        assert target_type_for(Action.REQUEST_HUMAN_APPROVAL) == "human"


# ── DecisionConfidence level derivation ──

class TestDecisionConfidence:
    def test_high_score(self):
        dc = DecisionConfidence(score=0.8)
        assert dc.level == ConfidenceLevel.HIGH

    def test_medium_score(self):
        dc = DecisionConfidence(score=0.6)
        assert dc.level == ConfidenceLevel.MEDIUM

    def test_low_score(self):
        dc = DecisionConfidence(score=0.2)
        assert dc.level == ConfidenceLevel.LOW

    def test_zero_score(self):
        dc = DecisionConfidence(score=0.0)
        assert dc.level == ConfidenceLevel.NONE

    def test_level_not_set_manually_is_ignored(self):
        # User passes level=HIGH but score is low — validator overrides
        dc = DecisionConfidence(score=0.1, level=ConfidenceLevel.HIGH)
        assert dc.level == ConfidenceLevel.LOW  # derived, not user-set


# ── ContractMetrics total_latency validator ──

class TestContractMetrics:
    def test_total_matches_sum_ok(self):
        m = ContractMetrics(decision_latency_ms=10.0, execution_latency_ms=5.0, total_latency_ms=15.0)
        assert m.total_latency_ms == 15.0

    def test_total_drift_in_prod_autocorrects(self, monkeypatch):
        from aion import config as cfg
        cfg._settings = None
        monkeypatch.setenv("AION_ENVIRONMENT", "prod")
        m = ContractMetrics(decision_latency_ms=10.0, execution_latency_ms=5.0, total_latency_ms=99.0)
        assert m.total_latency_ms == 15.0  # auto-corrected

    def test_total_drift_in_dev_raises(self, monkeypatch):
        from aion import config as cfg
        cfg._settings = None
        monkeypatch.setenv("AION_ENVIRONMENT", "dev")
        with pytest.raises(ValueError):
            ContractMetrics(decision_latency_ms=10.0, execution_latency_ms=5.0, total_latency_ms=99.0)
        cfg._settings = None  # reset


# ── RetryPolicy defaults ──

class TestRetryPolicy:
    def test_default_for_llm(self):
        p = default_retry_policy("llm")
        assert p.max_retries == 3
        assert p.timeout_ms == 30000

    def test_default_for_service(self):
        p = default_retry_policy("service")
        assert p.max_retries == 2
        assert p.timeout_ms == 5000

    def test_default_for_direct(self):
        assert default_retry_policy("direct") is None

    def test_default_for_human(self):
        assert default_retry_policy("human") is None


# ── ContractError HTTP mapping ──

class TestContractError:
    def test_policy_violation_is_403(self):
        err = ContractError(type=ErrorType.POLICY_VIOLATION)
        assert err.status_code() == 403

    def test_rate_limit_is_429(self):
        err = ContractError(type=ErrorType.RATE_LIMIT)
        assert err.status_code() == 429

    def test_upstream_retryable_is_503(self):
        err = ContractError(type=ErrorType.UPSTREAM_ERROR, retryable=True)
        assert err.status_code() == 503

    def test_upstream_non_retryable_is_502(self):
        err = ContractError(type=ErrorType.UPSTREAM_ERROR, retryable=False)
        assert err.status_code() == 502


# ── Capabilities ──

class TestCapabilities:
    def test_default_all_disabled(self):
        caps = Capabilities()
        assert not caps.control.applied
        assert not caps.routing.applied
        assert not caps.optimization.applied

    def test_all_applied(self):
        caps = Capabilities(
            control=CapabilityState(applied=True),
            routing=CapabilityState(applied=True),
            optimization=CapabilityState(applied=True),
        )
        assert caps.executed() == ["control", "routing", "optimization"]

    def test_mixed_states(self):
        caps = Capabilities(
            control=CapabilityState(applied=True),
            routing=CapabilityState(skipped=True, reason="disabled"),
            optimization=CapabilityState(failed=True, reason="degraded"),
        )
        assert caps.executed() == ["control"]
        assert "routing" in caps.skipped_list()


# ── ExtensionEntry governance ──

class TestExtensionEntry:
    def test_experimental_entry(self):
        e = ExtensionEntry(value={"foo": 1}, stage="experimental", added_version="1.0.0")
        assert e.stage == "experimental"
        assert e.deprecated_in is None

    def test_deprecated_entry(self):
        e = ExtensionEntry(
            value=None, stage="deprecated", added_version="1.0.0",
            deprecated_in="1.3.0", replaces="old_foo",
        )
        assert e.stage == "deprecated"


# ── DecisionContract ──

class TestDecisionContract:
    def _minimal_meta(self) -> ContractMeta:
        return ContractMeta(tenant="test", timestamp=time.time())

    def test_minimal_contract(self):
        c = DecisionContract(
            request_id="req_1",
            action=Action.BYPASS,
            meta=self._minimal_meta(),
        )
        assert c.contract_version == "1.0"
        assert c.side_effect_level == SideEffectLevel.NONE  # derived from BYPASS

    def test_side_effect_derived_from_action(self):
        c = DecisionContract(
            request_id="req_1",
            action=Action.CALL_SERVICE,
            side_effect_level=SideEffectLevel.NONE,  # user tries to override
            meta=self._minimal_meta(),
        )
        # Validator forces derivation
        assert c.side_effect_level == SideEffectLevel.EXTERNAL

    def test_final_output_for_llm(self):
        c = DecisionContract(
            request_id="req_1",
            action=Action.CALL_LLM,
            final_output=FinalOutput(
                target_type="llm",
                payload={"provider": "openai", "model": "gpt-4o"},
            ),
            meta=self._minimal_meta(),
        )
        assert c.final_output.target_type == "llm"
        assert c.final_output.payload_schema_version == "1.0"


# ── build_contract ──

class TestBuildContract:
    def _ctx(self, **kwargs) -> PipelineContext:
        ctx = PipelineContext(tenant="test")
        ctx.original_request = ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )
        for k, v in kwargs.items():
            setattr(ctx, k, v)
        return ctx

    def test_bypass_produces_bypass_action(self):
        ctx = self._ctx()
        ctx.set_bypass(ChatCompletionResponse(
            model="aion-bypass",
            choices=[ChatCompletionChoice(index=0, message=ChatMessage(role="assistant", content="hi"))],
        ))
        contract = build_contract(ctx, active_modules=["estixe"])
        assert contract.action == Action.BYPASS
        assert contract.side_effect_level == SideEffectLevel.NONE
        assert contract.capabilities.control.applied
        assert contract.final_output.target_type == "direct"

    def test_block_produces_error(self):
        ctx = self._ctx()
        ctx.set_block("prompt injection detected")
        contract = build_contract(ctx)
        assert contract.action == Action.BLOCK
        assert contract.error is not None
        assert contract.error.type == ErrorType.POLICY_VIOLATION

    def test_continue_produces_call_llm(self):
        ctx = self._ctx(selected_model="gpt-4o", selected_provider="openai")
        contract = build_contract(ctx, active_modules=["estixe", "nomos"])
        assert contract.action == Action.CALL_LLM
        assert contract.final_output.target_type == "llm"
        assert contract.final_output.payload["provider"] == "openai"
        assert contract.final_output.payload["model"] == "gpt-4o"

    def test_call_service_from_metadata(self):
        ctx = self._ctx()
        ctx.metadata["call_service_name"] = "crm_lookup"
        ctx.metadata["service_endpoint"] = "https://crm.internal/api"
        contract = build_contract(ctx)
        assert contract.action == Action.CALL_SERVICE
        assert contract.side_effect_level == SideEffectLevel.EXTERNAL
        assert contract.final_output.payload["service_name"] == "crm_lookup"

    def test_approval_from_metadata(self):
        ctx = self._ctx()
        ctx.metadata["approval_required"] = True
        ctx.metadata["approval_payload"] = {"approval_request_id": "apr_1"}
        contract = build_contract(ctx)
        assert contract.action == Action.REQUEST_HUMAN_APPROVAL
        assert contract.side_effect_level == SideEffectLevel.HUMAN

    def test_disabled_module_shows_skipped(self):
        ctx = self._ctx(selected_model="gpt-4o", selected_provider="openai")
        contract = build_contract(ctx, active_modules=["estixe"])  # nomos/metis missing
        assert contract.capabilities.control.applied
        assert contract.capabilities.routing.skipped
        assert contract.capabilities.optimization.skipped

    def test_failed_module_shows_failed(self):
        ctx = self._ctx(selected_model="gpt-4o", selected_provider="openai")
        ctx.metadata["failed_modules"] = ["nomos"]
        contract = build_contract(ctx, active_modules=["estixe", "nomos", "metis"])
        assert contract.capabilities.routing.failed
        assert contract.capabilities.routing.reason == "degraded"

    def test_metrics_total_is_sum(self):
        ctx = self._ctx(selected_model="gpt-4o", selected_provider="openai")
        contract = build_contract(
            ctx, active_modules=["estixe", "nomos"],
            decision_latency_ms=10.0, execution_latency_ms=20.0,
        )
        assert contract.meta.metrics.total_latency_ms == 30.0

    def test_operating_mode_propagates(self):
        ctx = self._ctx()
        ctx.set_bypass(ChatCompletionResponse(
            model="aion-bypass",
            choices=[ChatCompletionChoice(index=0, message=ChatMessage(role="assistant", content="hi"))],
        ))
        contract = build_contract(ctx, operating_mode="adaptive")
        assert contract.operating_mode == "adaptive"
        assert contract.meta.metrics.nemos_mode == "adaptive"


# ── Module result population (from Phase A module changes) ──

class TestModuleResultPopulation:
    """Verify that modules now populate typed results in context."""

    @pytest.mark.asyncio
    async def test_nomos_populates_result(self):
        from aion.nomos import NomosModule
        import os
        os.environ["OPENAI_API_KEY"] = "test-key"
        module = NomosModule()
        await module.initialize()

        ctx = PipelineContext(tenant="test")
        ctx.original_request = ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        await module.process(ctx.original_request, ctx)

        assert ctx.nomos_result is not None
        assert ctx.nomos_result.selected_model
        assert ctx.nomos_result.selected_provider

    @pytest.mark.asyncio
    async def test_metis_populates_result(self):
        from aion.metis import MetisPreModule
        module = MetisPreModule()

        ctx = PipelineContext(tenant="test")
        req = ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        await module.process(req, ctx)

        assert ctx.metis_result is not None
        assert ctx.metis_result.tokens_before >= 0
        assert ctx.metis_result.tokens_after >= 0
