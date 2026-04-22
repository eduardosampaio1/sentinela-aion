"""Mock LLM server — OpenAI-compatible, custo zero, 100% local.

Uso:
    python sim/mock_llm/server.py

Endpoints:
    POST /v1/chat/completions  (streaming e batch)
    GET  /v1/models
    GET  /health
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [mock-llm] %(message)s")
logger = logging.getLogger("mock-llm")

app = FastAPI(title="AION Mock LLM", version="1.0.0")

# ── Latência por modelo (ms base) — faz NOMOS routing ser visível ──
_LATENCIES: dict[str, float] = {
    "sim-gpt-4o-mini":    80,
    "sim-gpt-4o":        300,
    "sim-claude-sonnet": 500,
    "sim-gemini-flash":   60,
}
_DEFAULT_LATENCY = 150.0

# ── Respostas canned — patterns existentes + fintech BR ──
_CANNED: list[tuple[re.Pattern, str]] = [
    # Saudacoes
    (re.compile(r"^\s*(oi|hi|hello|ola|ol\u00e1)\b", re.I), "Ol\u00e1! Como posso ajudar?"),
    (re.compile(r"^\s*(bom dia|good morning)", re.I), "Bom dia! Como posso ajudar?"),
    (re.compile(r"^\s*(boa tarde|good afternoon)", re.I), "Boa tarde! No que posso ajudar?"),
    (re.compile(r"^\s*(boa noite|good evening|good night)", re.I), "Boa noite! Como posso ajudar?"),
    (re.compile(r"^\s*(obrigad|thanks|thank you|valeu)", re.I), "De nada! Fico \u00e0 disposi\u00e7\u00e3o."),
    (re.compile(r"^\s*(tchau|bye|goodbye|at\u00e9)", re.I), "At\u00e9 mais! Tenha um \u00f3timo dia."),

    # Fatos gerais
    (re.compile(r"capital do brasil", re.I), "A capital do Brasil \u00e9 Bras\u00edlia."),
    (re.compile(r"capital of france", re.I), "The capital of France is Paris."),
    (re.compile(r"factorial", re.I), "def factorial(n): return 1 if n <= 1 else n * factorial(n - 1)"),
    (re.compile(r"reverses? a string", re.I), "function reverseString(s) { return s.split('').reverse().join(''); }"),
    (re.compile(r"\bcircuit breaker\b", re.I),
     "O circuit breaker abre ap\u00f3s N falhas consecutivas e se recupera ap\u00f3s um timeout configur\u00e1vel."),
    (re.compile(r"\bCAP theorem\b", re.I),
     "CAP: escolha dois entre consist\u00eancia, disponibilidade e toler\u00e2ncia a parti\u00e7\u00e3o."),
    (re.compile(r"microservice", re.I),
     "Microsservi\u00e7os permitem deploy independente, diversidade tecnol\u00f3gica e isolamento de falhas."),
    (re.compile(r"\b2\s*\+\s*2\b", re.I), "2 + 2 = 4."),

    # Fintech BR
    (re.compile(r"pix.*limit|limit.*pix", re.I),
     "O limite padr\u00e3o PIX \u00e9 R$20.000 durante o dia e R$1.000 \u00e0 noite. "
     "Ajuste no app em Configura\u00e7\u00f5es > PIX > Limites."),
    (re.compile(r"chave.*pix|pix.*chave", re.I),
     "Suas chaves PIX cadastradas: CPF, e-mail e telefone. "
     "Para adicionar nova chave: \u00c1rea PIX > Minhas Chaves."),
    (re.compile(r"saldo|extrato|movimenta", re.I),
     "Saldo dispon\u00edvel: R$4.231,50. \u00daltima movimenta\u00e7\u00e3o: PIX recebido R$500,00 (ontem)."),
    (re.compile(r"cartao.*bloqueado|bloquei.*cartao|bloquear.*cart", re.I),
     "Cart\u00e3o bloqueado com sucesso. Para desbloquear: Cart\u00f5es > Gerenciar > Desbloquear."),
    (re.compile(r"investimento|cdb|tesouro|rendimento", re.I),
     "CDB dispon\u00edvel: 104% do CDI, liquidez di\u00e1ria. "
     "Para valores acima de R$50.000, consulte produtos de renda vari\u00e1vel."),
    (re.compile(r"limite.*credito|credito.*aumentar|aumentar.*limite", re.I),
     "An\u00e1lise conclu\u00edda. Seu limite pode ser aumentado para R$8.000. Confirmar?"),
    (re.compile(r"analise.*risco.*credito|credit.*risk|risco.*credito", re.I),
     "An\u00e1lise de risco de cr\u00e9dito: score 650, renda R$8.000, exposi\u00e7\u00e3o R$15.000. "
     "Recomenda\u00e7\u00e3o: aprova\u00e7\u00e3o condicional, limite R$3.000 por 90 dias, "
     "sujeito a monitoramento mensal conforme Resolu\u00e7\u00e3o BCB n\u00ba 4.966."),
    (re.compile(r"regulat|lgpd|compliance|audit", re.I),
     "Conforme LGPD Art. 7, o tratamento requer base legal. "
     "Nossa pol\u00edtica aplica minimiza\u00e7\u00e3o de dados e reten\u00e7\u00e3o m\u00e1xima de 5 anos. "
     "Log de acesso dispon\u00edvel em /v1/audit."),
    (re.compile(r"fraude|fraud|suspeito|suspicious", re.I),
     "Transa\u00e7\u00e3o sinalizada para an\u00e1lise de fraude. "
     "Equipe de seguran\u00e7a notificada. Ref: FRD-2026-0419."),
    (re.compile(r"ignore previous|disregard your|ignore suas|esque\u00e7a as", re.I),
     "N\u00e3o posso atender a essa solicita\u00e7\u00e3o."),
]


def _extract_prompt(messages: list[dict]) -> str:
    """Extrai o último conteúdo de usuário para matching."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part["text"]
            return str(content)
    return ""


def _get_response(prompt: str) -> str:
    for pattern, reply in _CANNED:
        if pattern.search(prompt):
            return reply
    h = hashlib.md5(prompt.encode("utf-8", errors="ignore")).hexdigest()[:6]
    words = prompt.strip().split()[:8]
    snippet = " ".join(words)
    return f"Sobre '{snippet}': resposta simulada pelo AION mock LLM (ref={h})."


def _count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _build_response(text: str, model: str, prompt_tokens: int, completion_tokens: int) -> dict:
    return {
        "id": f"mock-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


async def _sse_stream(text: str, model: str, request_id: str) -> AsyncIterator[bytes]:
    # Chunk inicial com role
    role_chunk = {
        "id": request_id, "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(role_chunk)}\n\n".encode()

    # Palavras uma a uma
    words = text.split()
    for i, word in enumerate(words):
        content = word + (" " if i < len(words) - 1 else "")
        chunk = {
            "id": request_id, "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()
        await asyncio.sleep(0.025)  # 25ms por palavra — streaming visível no demo

    # Chunk final
    done_chunk = {
        "id": request_id, "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done_chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "sim-gpt-4o-mini")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    prompt = _extract_prompt(messages)
    text = _get_response(prompt)

    # Latência proporcional ao prompt (faz METIS compression ser visível)
    base_latency = _LATENCIES.get(model, _DEFAULT_LATENCY)
    length_factor = min(len(prompt), 800) / 800.0
    latency_s = (base_latency + length_factor * base_latency * 0.5) / 1000.0
    await asyncio.sleep(latency_s)

    prompt_tokens = _count_tokens(prompt)
    completion_tokens = _count_tokens(text)

    logger.info("%-22s | tokens=%d+%d | stream=%-5s | %.0fms | %.40s…",
                model, prompt_tokens, completion_tokens, str(stream),
                latency_s * 1000, prompt.replace("\n", " "))

    if stream:
        request_id = f"mock-{uuid.uuid4().hex[:12]}"
        return StreamingResponse(
            _sse_stream(text, model, request_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return JSONResponse(_build_response(text, model, prompt_tokens, completion_tokens))


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    models = [
        {"id": m, "object": "model", "created": 1700000000, "owned_by": "aion-sim"}
        for m in _LATENCIES
    ]
    return JSONResponse({"object": "list", "data": models})


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "aion-mock-llm"})


if __name__ == "__main__":
    port = int(os.environ.get("MOCK_LLM_PORT", "8001"))
    print(f"[mock-llm] Iniciando na porta {port} — custo zero, 100% local")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
