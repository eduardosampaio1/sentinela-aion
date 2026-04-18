"""Tests for the prompt rewriter."""

import pytest

from aion.metis.rewriter import PromptRewriter
from aion.shared.schemas import ChatCompletionRequest, ChatMessage


def _make_request(content: str) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content=content)],
    )


@pytest.fixture
async def rewriter(tmp_path):
    """Rewriter with test rules."""
    rules = tmp_path / "rewrite_rules.yaml"
    rules.write_text("""
rules:
  - match_pattern: "resum|summarize"
    suffix: "Formato: bullet points."
    condition: "short"
    level: "light"

  - match_pattern: "implementa|implement"
    suffix: "Inclua type hints."
    condition: "short"
    level: "moderate"

  - match_pattern: "traduz|translate"
    suffix: "Mantenha o tom."
    condition: "any"
    level: "light"
""", encoding="utf-8")

    r = PromptRewriter()
    await r.load(tmp_path)
    return r


@pytest.mark.asyncio
async def test_rewrite_summary(rewriter):
    req = _make_request("resume esse texto")
    modified, result = rewriter.rewrite(req, rewrite_level="light")
    assert result.applied
    assert "bullet points" in modified.messages[-1].content
    assert "resume esse texto" in modified.messages[-1].content  # original preserved


@pytest.mark.asyncio
async def test_rewrite_off(rewriter):
    req = _make_request("resume esse texto")
    _, result = rewriter.rewrite(req, rewrite_level="off")
    assert not result.applied


@pytest.mark.asyncio
async def test_moderate_skipped_in_light(rewriter):
    req = _make_request("implementa binary search")
    _, result = rewriter.rewrite(req, rewrite_level="light")
    assert not result.applied  # moderate rule, light level


@pytest.mark.asyncio
async def test_moderate_applied_in_moderate(rewriter):
    req = _make_request("implementa binary search")
    modified, result = rewriter.rewrite(req, rewrite_level="moderate")
    assert result.applied
    assert "type hints" in modified.messages[-1].content


@pytest.mark.asyncio
async def test_long_prompt_skips_short_condition(rewriter):
    """Rules with condition='short' don't fire on long prompts."""
    long_text = "resume " + " ".join(["palavra"] * 60)
    req = _make_request(long_text)
    _, result = rewriter.rewrite(req, rewrite_level="light")
    assert not result.applied


@pytest.mark.asyncio
async def test_translate_any_condition(rewriter):
    """Rules with condition='any' fire regardless of length."""
    long_text = "traduz esse texto longo " + " ".join(["palavra"] * 60)
    req = _make_request(long_text)
    modified, result = rewriter.rewrite(req, rewrite_level="light")
    assert result.applied
    assert "tom" in modified.messages[-1].content


@pytest.mark.asyncio
async def test_no_match_no_rewrite(rewriter):
    req = _make_request("qual a capital do Brasil?")
    _, result = rewriter.rewrite(req, rewrite_level="moderate")
    assert not result.applied


@pytest.mark.asyncio
async def test_disable_rule(rewriter):
    req = _make_request("resume esse texto")
    rewriter.disable_rule("resum|summarize")
    _, result = rewriter.rewrite(req, rewrite_level="light")
    assert not result.applied

    # Re-enable
    rewriter.enable_rule("resum|summarize")
    _, result = rewriter.rewrite(req, rewrite_level="light")
    assert result.applied


@pytest.mark.asyncio
async def test_original_text_preserved(rewriter):
    """Rewriter must NEVER modify original user text — only append."""
    original = "resume esse texto pra mim"
    req = _make_request(original)
    modified, result = rewriter.rewrite(req, rewrite_level="light")
    assert result.applied
    assert modified.messages[-1].content.startswith(original)
