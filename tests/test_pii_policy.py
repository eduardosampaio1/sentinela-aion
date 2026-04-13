"""Tests for PII policy engine — allow/mask/block/audit per type, per tenant."""

from __future__ import annotations

import pytest

from aion.estixe.guardrails import Guardrails, GuardrailResult
from aion.shared.contracts import PiiAction, PiiPolicyConfig


# ── Fixtures ──

@pytest.fixture
def guardrails():
    return Guardrails()


CONTENT_CPF = "Meu CPF é 123.456.789-09"
CONTENT_EMAIL = "Meu email é joao@example.com"
CONTENT_MULTI = "CPF: 123.456.789-09, email: joao@example.com"
CONTENT_API_KEY = "Token: sk-abc1234567890abcdef"
CONTENT_CLEAN = "Hello, how are you?"


# ── Backward compatibility (no policy = mask all) ──

def test_no_policy_masks_all(guardrails: Guardrails):
    """Without a policy config, behavior is unchanged: mask everything."""
    result = guardrails.check_output(CONTENT_CPF)
    assert not result.safe
    assert "pii:cpf" in result.violations
    assert "[CPF_REDACTED]" in result.filtered_content
    assert "123.456.789-09" not in result.filtered_content


def test_none_policy_same_as_default(guardrails: Guardrails):
    result = guardrails.check_output(CONTENT_CPF, pii_policy=None)
    assert "[CPF_REDACTED]" in result.filtered_content


def test_default_mask_policy_same_as_no_policy(guardrails: Guardrails):
    policy = PiiPolicyConfig(default_action=PiiAction.MASK)
    result = guardrails.check_output(CONTENT_CPF, pii_policy=policy)
    assert "[CPF_REDACTED]" in result.filtered_content


# ── ALLOW action ──

def test_allow_detects_but_does_not_mask(guardrails: Guardrails):
    policy = PiiPolicyConfig(rules={"cpf": PiiAction.ALLOW})
    result = guardrails.check_output(CONTENT_CPF, pii_policy=policy)
    assert not result.safe  # still detected
    assert "pii:cpf" in result.violations
    assert "123.456.789-09" in result.filtered_content  # NOT masked


def test_allow_one_mask_another(guardrails: Guardrails):
    """Allow CPF but mask email."""
    policy = PiiPolicyConfig(
        default_action=PiiAction.MASK,
        rules={"cpf": PiiAction.ALLOW},
    )
    result = guardrails.check_output(CONTENT_MULTI, pii_policy=policy)
    assert "123.456.789-09" in result.filtered_content  # CPF allowed
    assert "[EMAIL_REDACTED]" in result.filtered_content  # email masked


# ── BLOCK action ──

def test_block_rejects_request(guardrails: Guardrails):
    policy = PiiPolicyConfig(rules={"cpf": PiiAction.BLOCK})
    result = guardrails.check_output(CONTENT_CPF, pii_policy=policy)
    assert result.blocked
    assert "cpf" in result.block_reason.lower()


def test_block_stops_early(guardrails: Guardrails):
    """When block triggers, processing stops immediately."""
    policy = PiiPolicyConfig(rules={"cpf": PiiAction.BLOCK})
    result = guardrails.check_output(CONTENT_MULTI, pii_policy=policy)
    assert result.blocked
    # email might or might not be in violations depending on pattern order,
    # but blocked flag must be set


def test_block_one_allow_another(guardrails: Guardrails):
    """Block email but allow CPF."""
    policy = PiiPolicyConfig(rules={
        "cpf": PiiAction.ALLOW,
        "email": PiiAction.BLOCK,
    })
    result = guardrails.check_output(CONTENT_MULTI, pii_policy=policy)
    assert result.blocked
    assert "email" in result.block_reason.lower()


# ── AUDIT action ──

def test_audit_detects_without_masking(guardrails: Guardrails):
    policy = PiiPolicyConfig(rules={"cpf": PiiAction.AUDIT})
    result = guardrails.check_output(CONTENT_CPF, pii_policy=policy)
    assert not result.safe
    assert "pii:cpf" in result.violations
    assert "cpf" in result.audited
    assert "123.456.789-09" in result.filtered_content  # NOT masked


def test_audit_plus_mask(guardrails: Guardrails):
    """Audit CPF, mask email."""
    policy = PiiPolicyConfig(
        default_action=PiiAction.MASK,
        rules={"cpf": PiiAction.AUDIT},
    )
    result = guardrails.check_output(CONTENT_MULTI, pii_policy=policy)
    assert "cpf" in result.audited
    assert "123.456.789-09" in result.filtered_content  # audited, not masked
    assert "[EMAIL_REDACTED]" in result.filtered_content  # masked


# ── MASK action (explicit) ──

def test_explicit_mask_same_as_default(guardrails: Guardrails):
    policy = PiiPolicyConfig(rules={"cpf": PiiAction.MASK})
    result = guardrails.check_output(CONTENT_CPF, pii_policy=policy)
    assert "[CPF_REDACTED]" in result.filtered_content


# ── PiiPolicyConfig ──

def test_policy_config_action_for_uses_default():
    policy = PiiPolicyConfig(default_action=PiiAction.BLOCK, rules={"cpf": PiiAction.ALLOW})
    assert policy.action_for("cpf") == PiiAction.ALLOW
    assert policy.action_for("email") == PiiAction.BLOCK  # falls back to default


def test_policy_config_from_dict():
    policy = PiiPolicyConfig(**{"default_action": "audit", "rules": {"cpf": "allow"}})
    assert policy.default_action == PiiAction.AUDIT
    assert policy.action_for("cpf") == PiiAction.ALLOW


# ── Clean content ──

def test_clean_content_no_violations(guardrails: Guardrails):
    policy = PiiPolicyConfig(default_action=PiiAction.BLOCK)
    result = guardrails.check_output(CONTENT_CLEAN, pii_policy=policy)
    assert result.safe
    assert not result.blocked
    assert result.filtered_content == CONTENT_CLEAN


# ── Default action = ALLOW (permissive tenant) ──

def test_default_allow_permits_all(guardrails: Guardrails):
    policy = PiiPolicyConfig(default_action=PiiAction.ALLOW)
    result = guardrails.check_output(CONTENT_MULTI, pii_policy=policy)
    assert not result.safe  # detected
    assert not result.blocked
    # content unchanged
    assert "123.456.789-09" in result.filtered_content
    assert "joao@example.com" in result.filtered_content
