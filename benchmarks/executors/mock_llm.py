"""Mock LLM — deterministic canned responses for benchmark runs without a live API key."""

from __future__ import annotations

import hashlib


_GREETINGS = {"oi", "olá", "ola", "hi", "hello", "bom dia", "boa tarde", "boa noite", "hey"}

_FALLBACK_POOL = [
    "Entendido. Com base no contexto solicitado, este benchmark retorna uma resposta de referencia.",
    "Processado. A resposta gerada para este prompt e um resultado de benchmark padronizado.",
    "Compreendido. Este e um resultado de benchmark para a solicitacao realizada.",
]


def mock_complete(prompt: str) -> tuple[str, int, int, float]:
    """Return (response_text, prompt_tokens, completion_tokens, latency_ms).

    Deterministic: same input always produces same output.
    """
    prompt_lower = prompt.strip().lower()

    # Canned greeting response
    if prompt_lower in _GREETINGS or any(prompt_lower.startswith(g + " ") for g in _GREETINGS):
        text = "Ola! Como posso ajudar?"
        pt = max(5, len(prompt.split()) + 2)
        ct = 8
        return text, pt, ct, 1.5

    # Deterministic fallback based on prompt hash
    h = int(hashlib.sha256(prompt.encode()).hexdigest(), 16) % len(_FALLBACK_POOL)
    text = _FALLBACK_POOL[h]
    pt = max(10, len(prompt.split()) + 2)
    ct = max(8, len(text.split()) + 2)
    return text, pt, ct, 15.0
