"""Deterministic mock LLM used by default (no cost, repeatable).

Produces responses that are shallow but semantically related to the prompt
so semantic similarity scoring has signal. Real evaluation should use --live.
"""

from __future__ import annotations

import hashlib
import re
import time

# Canned responses for common patterns — keeps mock semantically useful.
_CANNED: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(oi|hi|hello|ola)\b", re.I), "Ola! Como posso ajudar?"),
    (re.compile(r"^\s*(bom dia|good morning)", re.I), "Bom dia! Como posso ajudar?"),
    (re.compile(r"^\s*(boa tarde|good afternoon)", re.I), "Boa tarde!"),
    (re.compile(r"^\s*(boa noite|good evening|good night)", re.I), "Boa noite!"),
    (re.compile(r"^\s*(obrigad|thanks|thank you|valeu)", re.I), "De nada!"),
    (re.compile(r"^\s*(tchau|bye|goodbye|ate)", re.I), "Ate mais!"),
    (re.compile(r"capital do brasil", re.I), "A capital do Brasil e Brasilia."),
    (re.compile(r"capital of france", re.I), "The capital of France is Paris."),
    (re.compile(r"who wrote romeo", re.I), "Shakespeare wrote Romeo and Juliet."),
    (re.compile(r"mona lisa", re.I), "Leonardo da Vinci painted the Mona Lisa."),
    (re.compile(r"largest ocean", re.I), "The Pacific Ocean is the largest."),
    (re.compile(r"world war ii end", re.I), "World War II ended in 1945."),
    (re.compile(r"\b2\s*\+\s*2\b", re.I), "2 + 2 equals 4."),
    (re.compile(r"\b15\s*\*\s*7\b", re.I), "15 times 7 is 105."),
    (re.compile(r"\b144\s*/\s*12\b", re.I), "144 divided by 12 is 12."),
    (re.compile(r"boiling point of water", re.I), "Water boils at 100 Celsius."),
    (re.compile(r"planets.*solar system", re.I), "The solar system has 8 planets."),
    (re.compile(r"ignore previous|disregard your", re.I), "I cannot comply with that request."),
    (re.compile(r"photosynthesis", re.I), "Photosynthesis converts sunlight to energy in plants."),
    (re.compile(r"blockchain", re.I), "Blockchain is a distributed immutable ledger secured via cryptography."),
    (re.compile(r"rest.*api", re.I), "A REST API exposes resources via HTTP verbs."),
    (re.compile(r"\bSQL\b.*\bNoSQL\b", re.I), "SQL is relational and structured; NoSQL is flexible and schema-less."),
    (re.compile(r"microservice", re.I), "Microservices enable independent deployment, technology diversity, and fault isolation."),
    (re.compile(r"factorial", re.I), "def factorial(n): return 1 if n <= 1 else n * factorial(n - 1)"),
    (re.compile(r"reverses? a string", re.I), "function reverseString(s) { return s.split('').reverse().join(''); }"),
    (re.compile(r"numero.*primo|is_prime", re.I), "def is_prime(n): return n > 1 and all(n % i for i in range(2, int(n**0.5) + 1))"),
    (re.compile(r"\bcircuit breaker\b", re.I), "The circuit breaker opens after N failures and recovers after a timeout."),
    (re.compile(r"\bCAP theorem\b", re.I), "CAP: pick two of consistency, availability, and partition tolerance."),
    (re.compile(r"\bdocker\b.*\bimage\b.*\bcontainer\b", re.I), "An image is a template; a container is a running instance of an image."),
    (re.compile(r"TCP.*UDP|UDP.*TCP", re.I), "TCP is reliable and connection-oriented; UDP is fast but unreliable."),
]


def _fallback(prompt: str) -> str:
    """Generate a deterministic fallback response grounded in the prompt."""
    if not prompt.strip():
        return ""
    # Stable token count by prompt length
    h = hashlib.md5(prompt.encode("utf-8", errors="ignore")).hexdigest()[:6]
    words = prompt.strip().split()[:10]
    snippet = " ".join(words)
    return f"Sobre '{snippet}': resposta simulada para fins de benchmark (ref={h})."


def mock_complete(prompt: str, *, latency_ms: float = 10.0) -> tuple[str, int, int, float]:
    """Return (response_text, prompt_tokens, completion_tokens, simulated_latency_ms)."""
    # Simulate latency deterministically based on prompt length (longer = slower)
    length_factor = min(500, len(prompt)) / 500.0
    simulated = latency_ms + length_factor * 40.0

    response = None
    for pattern, reply in _CANNED:
        if pattern.search(prompt):
            response = reply
            break
    if response is None:
        response = _fallback(prompt)

    # Token estimation — use simple heuristic (tests don't need tiktoken precision)
    prompt_tokens = max(1, len(prompt) // 4)
    completion_tokens = max(1, len(response) // 4)

    # Small sleep to make latency observable without slowing the suite
    time.sleep(simulated / 1000.0 / 10.0)  # 10x compression

    return response, prompt_tokens, completion_tokens, simulated
