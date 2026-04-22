"""RiskClassifier — mapeia input para classes universais de risco.

Diferente do SemanticClassifier (que identifica intents específicas como greeting/farewell):
- Seeds definem ESTRUTURA DE COMPORTAMENTO, não frases por domínio
- Single-best-match v1: retorna a categoria de maior confiança acima do threshold (não multi-label)
- Ação via tabela de severidade, não por intent (critical/high → BLOCK)
- Agnóstico de domínio e idioma por design dos seeds

Melhorias v2:
- Normalização de input antes do embedding (lowercase, NFC, zero-width removal)
- Shadow mode: categoria em shadow=true observa mas não bloqueia
- threshold_overrides: por-tenant overrides de threshold passados via classify()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from aion.config import EstixeSettings
from aion.estixe._normalize import normalize_input
from aion.shared.embeddings import get_embedding_model

logger = logging.getLogger("aion.estixe.risk_classifier")


@dataclass
class RiskMatch:
    """Result of risk classification."""
    category: str        # "instruction_override", "fraud_enablement", ...
    risk_level: str      # "critical" | "high"
    confidence: float
    matched_seed: str
    threshold_used: float = 0.0   # effective threshold applied — facilita debug e tuning
    description: str = ""
    shadow: bool = False          # True → match observed but not enforced (shadow mode)


@dataclass
class RiskDefinition:
    """A risk category loaded from risk_taxonomy.yaml."""
    name: str
    risk_level: str
    threshold: float
    description: str
    seeds: list[str]
    shadow: bool = False                                        # shadow mode flag
    embeddings: Optional[np.ndarray] = field(default=None, repr=False)


class RiskClassifier:
    """Classifies user input into universal structural risk categories.

    Unlike SemanticClassifier (domain-specific intents), RiskClassifier
    uses seeds that describe BEHAVIORAL STRUCTURE — patterns that are risky
    regardless of language, domain, or phrasing style.

    Action table (implemented in estixe/__init__.py):
        critical + confidence >= threshold → BLOCK  (unless shadow=True)
        high     + confidence >= threshold → BLOCK  (unless shadow=True)
        shadow=True                        → FLAG + CONTINUE (observing)
        no match above threshold           → CONTINUE (other layers still run)

    threshold_overrides (per-tenant): dict {category_name: float} passed at classify()
    time to override the per-category thresholds from YAML without mutating shared state.
    """

    def __init__(self, settings: EstixeSettings) -> None:
        self._settings = settings
        self._risks: list[RiskDefinition] = []
        # Classification-level cache: <hash(normalized+overrides)> -> RiskMatch|None
        # Maior ROI que cache de embeddings: queries repetidas pulam matmul + argmax
        # de TODAS as categorias, nao so o encode.
        import collections
        self._classify_cache: "collections.OrderedDict[str, Optional[RiskMatch]]" = collections.OrderedDict()
        self._classify_cache_max = 2000
        self._classify_cache_hits = 0
        self._classify_cache_misses = 0

    async def load(self) -> None:
        """Load risk taxonomy. Uses shared embedding model singleton.

        If model is unavailable (missing library, download failure),
        risks are still loaded from YAML but without embeddings — classify()
        will return None for all inputs (no blocking, but no crash either).
        """
        model = get_embedding_model()
        if not model.loaded:
            await model.load()  # does NOT raise — sets model._load_failed instead
            if model.loaded:
                logger.info("RiskClassifier: shared embedding model ready: %s", model.model_name)
            else:
                logger.warning("RiskClassifier: embedding model unavailable — risk classification disabled")

        taxonomy_path = Path(self._settings.intents_path).parent / "risk_taxonomy.yaml"
        if taxonomy_path.exists():
            await self._load_taxonomy(taxonomy_path)
        else:
            logger.warning("risk_taxonomy.yaml not found: %s", taxonomy_path)

    async def _load_taxonomy(self, path: Path) -> None:
        """Load risk definitions and pre-compute seed embeddings.

        Seeds are normalized before encoding — this ensures the same embedding
        space is used for both seeds (at load time) and inputs (at classify time).
        """
        model = get_embedding_model()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._risks = []
        for name, cfg in data.get("risks", {}).items():
            seeds = cfg.get("seeds", [])
            shadow = bool(cfg.get("shadow", False))
            risk = RiskDefinition(
                name=name,
                risk_level=cfg.get("risk_level", "high"),
                threshold=cfg.get("threshold", self._settings.risk_check_threshold),
                description=cfg.get("description", ""),
                seeds=seeds,
                shadow=shadow,
            )
            if seeds and model.loaded:
                # Normalize seeds before encoding — same normalization applied to inputs
                normalized_seeds = [normalize_input(s) for s in seeds]
                risk.embeddings = model.encode(normalized_seeds, normalize=True)
            self._risks.append(risk)

        shadow_count = sum(1 for r in self._risks if r.shadow)
        total_seeds = sum(len(r.seeds) for r in self._risks)
        logger.info(
            "Risk taxonomy loaded: %d categories (%d shadow), %d total seeds",
            len(self._risks), shadow_count, total_seeds,
        )

    def classify(
        self,
        text: str,
        threshold_overrides: dict[str, float] | None = None,
    ) -> Optional[RiskMatch]:
        """Return the highest-confidence risk category above its threshold, or None.

        Single-best-match: scans all categories, returns the one with the highest
        confidence that exceeds its effective threshold. Returns None if no
        category matches (other pipeline layers still run).

        Args:
            text: Raw user input — will be normalized internally.
            threshold_overrides: Per-category threshold overrides, e.g.
                {"fraud_enablement": 0.70}. Overrides YAML threshold for that
                category without mutating shared state (safe under concurrent load).
                Useful for per-tenant sensitivity tuning.
        """
        model = get_embedding_model()
        if not model.loaded or not self._risks:
            return None

        # Normalize before encoding — same transform applied to seeds at load time
        normalized = normalize_input(text)

        # Cache hit: skip encode + matmul + argmax. Maior speedup em stress test
        # (queries repetidas como "oi", "give me admin access", "qual meu saldo"
        # batem cache e retornam em ~10us).
        if self._settings.cache_embeddings:
            import hashlib
            override_key = ""
            if threshold_overrides:
                override_key = ":" + "|".join(f"{k}={v:.3f}" for k, v in sorted(threshold_overrides.items()))
            cache_key = hashlib.sha256((normalized + override_key).encode()).hexdigest()

            if cache_key in self._classify_cache:
                self._classify_cache.move_to_end(cache_key)
                self._classify_cache_hits += 1
                return self._classify_cache[cache_key]
            self._classify_cache_misses += 1

        input_emb = model.encode_single(
            normalized, normalize=True, use_cache=self._settings.cache_embeddings,
        )

        best: Optional[RiskMatch] = None
        best_conf = 0.0

        for risk in self._risks:
            if risk.embeddings is None:
                continue

            # Cosine similarity (embeddings are unit-normalized, so dot product = cosine)
            sims = risk.embeddings @ input_emb
            idx = int(np.argmax(sims))
            conf = float(sims[idx])

            # Resolve effective threshold: override > YAML default
            effective_threshold = (
                threshold_overrides.get(risk.name, risk.threshold)
                if threshold_overrides
                else risk.threshold
            )

            if conf >= effective_threshold and conf > best_conf:
                best_conf = conf
                best = RiskMatch(
                    category=risk.name,
                    risk_level=risk.risk_level,
                    confidence=conf,
                    matched_seed=risk.seeds[idx],
                    threshold_used=effective_threshold,
                    description=risk.description,
                    shadow=risk.shadow,
                )

        if best:
            level_log = "SHADOW RISK" if best.shadow else "RISK"
            logger.info(
                "%s: category='%s' level='%s' conf=%.3f threshold=%.2f shadow=%s input='%s'",
                level_log, best.category, best.risk_level, best.confidence,
                best.threshold_used, best.shadow, text[:80],
            )

        # Armazena resultado (incluindo None = "sem match") no cache LRU
        if self._settings.cache_embeddings:
            self._classify_cache[cache_key] = best
            while len(self._classify_cache) > self._classify_cache_max:
                self._classify_cache.popitem(last=False)

        return best

    async def reload(self) -> None:
        """Reload risk taxonomy from disk (hot-reload).

        Clears the embedding cache and re-encodes all seeds from the current
        risk_taxonomy.yaml on disk. Called by the /v1/estixe/intents/reload
        endpoint alongside SemanticClassifier.reload().
        """
        model = get_embedding_model()
        model.clear_cache()
        self._classify_cache.clear()
        self._classify_cache_hits = 0
        self._classify_cache_misses = 0
        taxonomy_path = Path(self._settings.intents_path).parent / "risk_taxonomy.yaml"
        if taxonomy_path.exists():
            await self._load_taxonomy(taxonomy_path)
            logger.info(
                "Risk taxonomy reloaded: %d categories, %d seeds",
                self.category_count, self.seed_count,
            )
        else:
            logger.warning("reload(): risk_taxonomy.yaml not found: %s", taxonomy_path)

    @property
    def category_count(self) -> int:
        return len(self._risks)

    @property
    def seed_count(self) -> int:
        return sum(len(r.seeds) for r in self._risks)

    @property
    def shadow_category_count(self) -> int:
        return sum(1 for r in self._risks if r.shadow)

    @property
    def cache_stats(self) -> dict:
        """Classification cache hit/miss stats (for /health and observability)."""
        total = self._classify_cache_hits + self._classify_cache_misses
        hit_rate = self._classify_cache_hits / total if total else 0.0
        return {
            "size": len(self._classify_cache),
            "max": self._classify_cache_max,
            "hits": self._classify_cache_hits,
            "misses": self._classify_cache_misses,
            "hit_rate": round(hit_rate, 3),
        }
