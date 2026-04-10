"""Tests for shared schemas."""

from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    Decision,
    PipelineContext,
    UsageInfo,
)


def test_chat_request_parsing():
    req = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hello")],
    )
    assert req.model == "gpt-4o-mini"
    assert len(req.messages) == 1
    assert req.stream is False


def test_chat_request_stream():
    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    assert req.stream is True


def test_chat_response_creation():
    resp = ChatCompletionResponse(
        model="test",
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(role="assistant", content="Hello!"),
            )
        ],
        usage=UsageInfo(prompt_tokens=5, completion_tokens=1, total_tokens=6),
    )
    assert resp.object == "chat.completion"
    assert resp.choices[0].message.content == "Hello!"
    assert resp.id.startswith("aion-")


def test_pipeline_context_bypass():
    ctx = PipelineContext()
    assert ctx.decision == Decision.CONTINUE

    resp = ChatCompletionResponse(model="bypass")
    ctx.set_bypass(resp)
    assert ctx.decision == Decision.BYPASS
    assert ctx.bypass_response is not None


def test_pipeline_context_block():
    ctx = PipelineContext()
    ctx.set_block("test reason")
    assert ctx.decision == Decision.BLOCK
    assert ctx.metadata["block_reason"] == "test reason"


def test_pipeline_context_tenant():
    ctx = PipelineContext(tenant="acme-corp")
    assert ctx.tenant == "acme-corp"
    assert ctx.request_id  # auto-generated
