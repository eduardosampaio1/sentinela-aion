"""Bypass intent suggestions — auto-discovery via clustering of passthrough requests.

Identifies clusters of similar user messages that went to LLM (passthrough) and
suggests them as new bypass intent candidates. Human-in-the-loop: suggestions
are proposed, user approves/rejects.

Privacy model:
- Sampler is OPT-IN (AION_SUGGESTIONS_ENABLED).
- Stores embedding + PII-filtered user message + response length + cost.
- Bounded buffer per tenant (default 1000 entries).
- User can delete tenant data via existing /v1/data/{tenant} endpoint.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger("aion.estixe.suggestions")


@dataclass
class PassthroughSample:
    """A single sampled passthrough request."""
    timestamp: float
    user_message: str  # PII-filtered
    embedding: np.ndarray
    response_length: int
    cost: float
    tenant: str


@dataclass
class IntentSuggestion:
    """A clustered suggestion for a new bypass intent."""
    id: str  # hash of cluster centroid
    cluster_size: int
    sample_messages: list[str]  # up to 5 PII-filtered examples
    suggested_intent_name: str  # heuristic from common words
    suggested_response: str  # placeholder — user edits
    estimated_daily_savings: float
    avg_response_length: int
    confidence: float  # 0-1, based on cluster tightness

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cluster_size": self.cluster_size,
            "sample_messages": self.sample_messages,
            "suggested_intent_name": self.suggested_intent_name,
            "suggested_response": self.suggested_response,
            "estimated_daily_savings": round(self.estimated_daily_savings, 4),
            "avg_response_length": self.avg_response_length,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TenantState:
    """Per-tenant suggestion state."""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    rejected_ids: set[str] = field(default_factory=set)
    approved_ids: set[str] = field(default_factory=set)


class SuggestionEngine:
    """Clusters passthrough requests and suggests new bypass intents."""

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.85,
        min_cluster_size: int = 3,
        max_samples_per_suggestion: int = 5,
        sampling_rate: float = 1.0,  # 1.0 = sample every passthrough
    ) -> None:
        self._threshold = similarity_threshold
        self._min_cluster_size = min_cluster_size
        self._max_samples = max_samples_per_suggestion
        self._sampling_rate = sampling_rate
        self._state: dict[str, TenantState] = {}

    def _get_state(self, tenant: str) -> TenantState:
        if tenant not in self._state:
            self._state[tenant] = TenantState()
        return self._state[tenant]

    def record(
        self,
        tenant: str,
        user_message: str,
        response_length: int,
        cost: float,
    ) -> None:
        """Record a passthrough sample. Fire-and-forget — never raises."""
        try:
            # Sampling rate gate
            if self._sampling_rate < 1.0:
                import random
                if random.random() > self._sampling_rate:
                    return

            # Embed via shared model
            from aion.shared.embeddings import get_embedding_model
            model = get_embedding_model()
            if not model.loaded:
                return  # silently skip if model unavailable

            # PII sanitize before storing
            sanitized = self._sanitize(user_message)
            if not sanitized.strip():
                return

            embedding = model.encode_single(sanitized, normalize=True)

            sample = PassthroughSample(
                timestamp=time.time(),
                user_message=sanitized,
                embedding=embedding,
                response_length=response_length,
                cost=cost,
                tenant=tenant,
            )
            self._get_state(tenant).samples.append(sample)
        except Exception:
            logger.debug("Suggestion sample failed — non-critical", exc_info=True)

    def generate(self, tenant: str) -> list[IntentSuggestion]:
        """Cluster samples for a tenant and return suggestions."""
        state = self._get_state(tenant)
        samples = list(state.samples)

        if len(samples) < self._min_cluster_size:
            return []

        clusters = self._greedy_cluster(samples)
        suggestions: list[IntentSuggestion] = []

        for cluster in clusters:
            if len(cluster) < self._min_cluster_size:
                continue

            centroid = self._compute_centroid(cluster)
            cluster_id = self._cluster_id(centroid)

            # Skip rejected or already approved clusters
            if cluster_id in state.rejected_ids:
                continue
            if cluster_id in state.approved_ids:
                continue

            sample_messages = self._select_representative_messages(cluster)
            intent_name = self._suggest_intent_name(sample_messages)
            avg_response_len = int(np.mean([s.response_length for s in cluster]))
            avg_cost = float(np.mean([s.cost for s in cluster]))
            estimated_daily = self._estimate_daily_savings(len(cluster), avg_cost, samples)
            confidence = self._compute_confidence(cluster, centroid)

            suggestions.append(IntentSuggestion(
                id=cluster_id,
                cluster_size=len(cluster),
                sample_messages=sample_messages,
                suggested_intent_name=intent_name,
                suggested_response="Edite esta resposta",  # user will customize
                estimated_daily_savings=estimated_daily,
                avg_response_length=avg_response_len,
                confidence=confidence,
            ))

        # Sort by savings potential
        suggestions.sort(key=lambda s: s.estimated_daily_savings, reverse=True)
        return suggestions

    def approve(self, tenant: str, suggestion_id: str) -> bool:
        """Mark suggestion as approved. Returns True if it existed."""
        state = self._get_state(tenant)
        # Verify it's a known cluster
        for s in self.generate(tenant):
            if s.id == suggestion_id:
                state.approved_ids.add(suggestion_id)
                logger.info(
                    '{"event":"suggestion_approved","tenant":"%s","id":"%s"}',
                    tenant, suggestion_id,
                )
                return True
        return False

    def reject(self, tenant: str, suggestion_id: str) -> bool:
        """Mark suggestion as rejected so it doesn't resurface."""
        state = self._get_state(tenant)
        state.rejected_ids.add(suggestion_id)
        logger.info(
            '{"event":"suggestion_rejected","tenant":"%s","id":"%s"}',
            tenant, suggestion_id,
        )
        return True

    def delete_tenant(self, tenant: str) -> None:
        """Delete all data for a tenant (LGPD)."""
        self._state.pop(tenant, None)

    @property
    def total_samples(self) -> int:
        return sum(len(s.samples) for s in self._state.values())

    def tenant_sample_count(self, tenant: str) -> int:
        return len(self._get_state(tenant).samples)

    # ── internals ──

    def _greedy_cluster(self, samples: list[PassthroughSample]) -> list[list[PassthroughSample]]:
        """Single-pass greedy clustering by cosine similarity."""
        clusters: list[list[PassthroughSample]] = []
        centroids: list[np.ndarray] = []

        for sample in samples:
            # Find best matching cluster
            best_idx = -1
            best_sim = self._threshold
            for i, centroid in enumerate(centroids):
                sim = float(sample.embedding @ centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_idx = i

            if best_idx >= 0:
                clusters[best_idx].append(sample)
                # Update centroid incrementally (running mean, re-normalized)
                old_c = centroids[best_idx]
                n = len(clusters[best_idx])
                new_c = old_c + (sample.embedding - old_c) / n
                centroids[best_idx] = new_c / (np.linalg.norm(new_c) + 1e-9)
            else:
                clusters.append([sample])
                centroids.append(sample.embedding.copy())

        return clusters

    @staticmethod
    def _compute_centroid(cluster: list[PassthroughSample]) -> np.ndarray:
        embs = np.stack([s.embedding for s in cluster])
        centroid = embs.mean(axis=0)
        return centroid / (np.linalg.norm(centroid) + 1e-9)

    @staticmethod
    def _cluster_id(centroid: np.ndarray) -> str:
        """Stable id from centroid — hash of rounded bytes."""
        rounded = np.round(centroid, decimals=3).astype(np.float32)
        return hashlib.sha256(rounded.tobytes()).hexdigest()[:16]

    def _select_representative_messages(self, cluster: list[PassthroughSample]) -> list[str]:
        """Pick up to N messages closest to centroid, diverse enough."""
        centroid = self._compute_centroid(cluster)
        # Sort by similarity to centroid
        scored = sorted(
            cluster,
            key=lambda s: float(s.embedding @ centroid),
            reverse=True,
        )
        # Take top N, deduplicated by normalized text
        seen: set[str] = set()
        picks: list[str] = []
        for s in scored:
            norm = re.sub(r"\s+", " ", s.user_message.strip().lower())
            if norm in seen:
                continue
            seen.add(norm)
            picks.append(s.user_message)
            if len(picks) >= self._max_samples:
                break
        return picks

    @staticmethod
    def _suggest_intent_name(messages: list[str]) -> str:
        """Extract most common meaningful word as intent name heuristic."""
        # Tokenize, remove stopwords, get most common
        stopwords = {
            "a", "o", "e", "de", "do", "da", "que", "em", "para", "com", "no", "na",
            "um", "uma", "os", "as", "por", "se", "eu", "voce", "me", "quero", "qual",
            "quais", "como", "the", "is", "a", "of", "to", "and", "for", "in", "on",
            "at", "you", "i", "my", "what", "how", "can", "need", "want", "me",
        }
        words: list[str] = []
        for msg in messages:
            for w in re.findall(r"\w+", msg.lower()):
                if len(w) > 2 and w not in stopwords:
                    words.append(w)
        if not words:
            return "novo_intent"
        counter = Counter(words)
        top_word = counter.most_common(1)[0][0]
        return f"intent_{top_word}"

    def _estimate_daily_savings(
        self, cluster_size: int, avg_cost: float, all_samples: list[PassthroughSample],
    ) -> float:
        """Projected daily savings if this cluster became a bypass."""
        if not all_samples:
            return 0.0
        # How many samples per day based on timespan of buffer
        span_seconds = all_samples[-1].timestamp - all_samples[0].timestamp
        if span_seconds <= 0:
            return cluster_size * avg_cost
        daily_multiplier = 86400 / span_seconds
        return cluster_size * avg_cost * daily_multiplier

    @staticmethod
    def _compute_confidence(cluster: list[PassthroughSample], centroid: np.ndarray) -> float:
        """Cluster tightness — mean similarity to centroid."""
        sims = [float(s.embedding @ centroid) for s in cluster]
        return float(np.mean(sims))

    @staticmethod
    def _sanitize(text: str) -> str:
        """Apply existing PII guardrails to text before storing."""
        try:
            from aion.estixe.guardrails import Guardrails
            g = Guardrails()
            result = g.check_output(text)
            return result.filtered_content
        except Exception:
            return text


# ── Singleton ──

_instance: Optional[SuggestionEngine] = None


def get_suggestion_engine() -> SuggestionEngine:
    global _instance
    if _instance is None:
        _instance = SuggestionEngine()
    return _instance
