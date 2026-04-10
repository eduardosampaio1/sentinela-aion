"""Tests for ESTIXE guardrails."""

from aion.estixe.guardrails import Guardrails


def test_detect_email():
    g = Guardrails()
    result = g.check_output("Contact me at john@example.com for details")
    assert not result.safe
    assert "pii:email" in result.violations
    assert "EMAIL_REDACTED" in result.filtered_content


def test_detect_phone():
    g = Guardrails()
    result = g.check_output("Call me at 555-123-4567")
    assert not result.safe
    assert "pii:phone_number" in result.violations


def test_detect_credit_card():
    g = Guardrails()
    result = g.check_output("Card number: 4111 1111 1111 1111")
    assert not result.safe
    assert "pii:credit_card" in result.violations
    assert "CREDIT_CARD_REDACTED" in result.filtered_content


def test_safe_content():
    g = Guardrails()
    result = g.check_output("The capital of France is Paris.")
    assert result.safe
    assert not result.violations


def test_token_limit():
    g = Guardrails()
    assert g.check_token_limit(1000) is True
    assert g.check_token_limit(5000) is False  # default max is 4096
