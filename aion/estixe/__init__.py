"""ESTIXE — Control & Bypass Engine. Bloqueia, bypassa, aplica politica, reduz risco.

Arquitetura de decisão (4 sinais independentes):
    S1: regex/keyword signals   (policies.yaml      — determinístico)
    S2: PII signals             (guardrails         — determinístico)
    S3: structural risk signals (risk_taxonomy.yaml — probabilístico)
    S4: intent signals          (intents.yaml       — probabilístico)

Tabela de ação canônica:
    critical + confidence >= threshold → BLOCK
    high     + confidence >= threshold → BLOCK
    shadow=True (qualquer nível)       → FLAG + CONTINUE (modo observação)
    medium   + confidence >= threshold → FLAG + CONTINUE
    nenhum sinal acima do threshold    → CONTINUE

Output guard (non-streaming, v1):
    S2': PII no output do LLM  → MASK ou BLOCK
    S3': risco estrutural no output → BLOCK (evita vazamento de instrução/política)

Melhorias v2:
    - Normalização de input antes da classificação (_normalize.py)
    - Shadow mode: categoria shadow=true observa mas não bloqueia
    - Threshold por tenant: estixe_thresholds em context.metadata
    - Velocity detection: N blocks em T segundos → tighten thresholds automaticamente
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aion.config import get_estixe_settings
from aion.estixe.bypass import BypassEngine
from aion.estixe.classifier import SemanticClassifier
from aion.estixe.guardrails import Guardrails
from aion.estixe.output_guard import OutputGuard
from aion.estixe.policy import PolicyEngine
from aion.estixe.risk_classifier import RiskClassifier
from aion.estixe.velocity import VelocityTracker
from aion.shared.contracts import EstixeAction, EstixeResult, PiiPolicyConfig
from aion.shared.schemas import ChatCompletionRequest, Decision, PipelineContext
from aion.shared.tokens import extract_user_message

if TYPE_CHECKING:
    pass

logger = logging.getLogger("aion.estixe")


class EstixeModule:
    """ESTIXE pipeline module — runs classification, policy, and bypass."""

    name = "estixe"

    def __init__(self) -> None:
        settings = get_estixe_settings()
        self._settings = settings
        self._classifier = SemanticClassifier(settings)
        self._risk_classifier = RiskClassifier(settings)
        self._bypass = BypassEngine(self._classifier)
        self._policy = PolicyEngine()
        self._guardrails = Guardrails()
        self._initialized = False
        self._classifier_degraded: bool = False  # True if embedding model failed to load
        self._velocity = VelocityTracker(settings)
        self._output_guard = OutputGuard(self._guardrails, self._risk_classifier, settings)
        # DecisionCache — fast path. Cacheia decisão final do pipeline.
        # Hit = ~10µs. Miss = full pipeline (~50ms com embedding).
        # Meta em produção: >80% hit rate → throughput multiplica ~500x.
        from aion.estixe.decision_cache import DecisionCache
        self._decision_cache = DecisionCache(max_size=10_000, ttl_seconds=300)
        # Métricas por tier — observabilidade de onde o tempo vai
        self._tier_hits = {"cache": 0, "policy": 0, "pii_block": 0, "risk": 0, "intent": 0, "continue": 0}

    @property
    def _classifier_ready(self) -> bool:
        """True if semantic classifier has a loaded embedding model."""
        from aion.shared.embeddings import get_embedding_model
        return get_embedding_model().loaded

    async def initialize(self) -> None:
        """Initialize ESTIXE sub-components independently.

        Partial success is OK: if classifier fails (no embedding model),
        PII guardrails and policy engine still work (regex-based).
        Module is always marked initialized to avoid retry loops.
        """
        if self._initialized:
            return

        # Policy engine (regex/YAML — no ML dependency)
        try:
            await self._policy.load()
        except Exception:
            logger.warning("ESTIXE: policy engine failed to load", exc_info=True)

        # Semantic classifier + risk classifier (require embedding model — may fail gracefully)
        try:
            await self._classifier.load()
            await self._risk_classifier.load()
        except Exception:
            self._classifier_degraded = True
            logger.warning(
                "ESTIXE: semantic/risk classifier unavailable — bypass and risk detection disabled, "
                "PII and policy enforcement still active",
                exc_info=True,
            )

        # Always mark initialized (PII + policy work without classifier)
        self._initialized = True
        logger.info(
            "ESTIXE initialized (classifier=%s, risk_classifier=%s, categories=%d, shadow=%d)",
            "active" if self._classifier_ready else "unavailable",
            "active" if self._classifier_ready else "unavailable",
            self._risk_classifier.category_count,
            self._risk_classifier.shadow_category_count,
        )

    @property
    def health(self) -> dict:
        """Health status of all ESTIXE sub-components.

        Used by /health endpoint to report degradation.
        """
        classifier_status = "active" if self._classifier_ready else "unavailable"
        return {
            "classifier": classifier_status,
            "risk_classifier": classifier_status,
            "risk_categories": self._risk_classifier.category_count,
            "risk_shadow_categories": self._risk_classifier.shadow_category_count,
            "risk_seeds": self._risk_classifier.seed_count,
            "risk_classify_cache": self._risk_classifier.cache_stats,
            "decision_cache": self._decision_cache.stats,
            "tier_hits": dict(self._tier_hits),
            "policy": "active",  # policy engine is always regex-based
            "guardrails": "active",  # guardrails are always regex-based
            "velocity_enabled": self._settings.velocity_enabled,
            "degraded": self._classifier_degraded,
        }

    async def reload(self) -> dict:
        """Hot-reload intents AND risk taxonomy from disk.

        Called by /v1/estixe/intents/reload. Reloads both classifiers so that
        changes to intents.yaml and risk_taxonomy.yaml take effect without restart.
        Returns a summary dict for the API response.
        """
        await self._classifier.reload()
        await self._risk_classifier.reload()
        # Invalida decision cache: taxonomy/intents mudaram, decisões cacheadas
        # podem estar stale (mesma query agora daria decisão diferente).
        self._decision_cache.invalidate_all()
        # F-22: invalidate the contract-builder YAML version cache so the next
        # contract reflects the new intents/policies versions in `provenance`.
        try:
            from aion.contract import clear_provenance_cache
            clear_provenance_cache()
        except Exception:
            pass
        logger.info(
            "ESTIXE reloaded: intents=%d examples=%d | risk_categories=%d seeds=%d | decision_cache cleared",
            self._classifier.intent_count,
            self._classifier.example_count,
            self._risk_classifier.category_count,
            self._risk_classifier.seed_count,
        )
        return {
            "intents": self._classifier.intent_count,
            "examples": self._classifier.example_count,
            "risk_categories": self._risk_classifier.category_count,
            "risk_seeds": self._risk_classifier.seed_count,
            "risk_shadow_categories": self._risk_classifier.shadow_category_count,
        }

    async def process(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        if not self._initialized:
            await self.initialize()

        # Initialize the formal result — populated progressively
        result = EstixeResult(action=EstixeAction.CONTINUE)

        # Extract user message using shared utility
        user_message = extract_user_message(request)
        if not user_message:
            context.estixe_result = result
            return context

        # ──────────────────────────────────────────────
        # TIER 1 — DecisionCache (fast path, ~10µs)
        # ──────────────────────────────────────────────
        # Cacheia decisão final do pipeline. Hit = retorna direto, sem embedding.
        # Key é hash(tenant | normalized_input | policy_version). Múltiplas réplicas
        # podem compartilhar via Redis em V2 (hoje cada réplica tem seu cache local).
        from aion.estixe._normalize import normalize_input
        normalized = normalize_input(user_message)
        if len(request.messages) == 1:  # Sem histórico = cache seguro
            cached = await self._decision_cache.get(context.tenant, normalized)
            if cached is not None:
                self._tier_hits["cache"] += 1
                context.estixe_result = cached.to_result()
                # Aplica efeitos do cached (block/bypass) no context
                if cached.action == EstixeAction.BLOCK:
                    context.set_block(cached.block_reason or "Cached block decision")
                # Marca origem no metadata para telemetria
                context.metadata["decision_source"] = "cache"
                return context

        # Resolve PII policy once — used in multiple places below
        pii_policy = self._resolve_pii_policy(context)

        # Resolve threshold overrides (tenant-specific + velocity tightening) ONCE up-front.
        # Passed to every _risk_classifier.classify() call in this request — ensures system
        # message scan, main input scan, and intent classifier all use the same thresholds.
        tenant_thresholds: dict[str, float] = context.metadata.get("estixe_thresholds") or {}
        threshold_overrides = await self._velocity.resolve_threshold_overrides(
            context, tenant_thresholds, self._risk_classifier._risks
        )

        # ── Multi-turn: risk escalation + intent continuity ──
        # Multi-turn risk escalation: tighten thresholds when prior turn had high risk.
        turn_ctx = context.metadata.get("turn_context")
        prior_intent: str | None = None
        if turn_ctx is not None:
            prior_risk = turn_ctx.max_risk_score
            if prior_risk >= 0.7:
                delta = min(prior_risk - 0.65, 0.10)
                threshold_overrides = {
                    k: max(0.55, v - delta)
                    for k, v in (threshold_overrides or {}).items()
                }
                context.metadata["turn_risk_escalation"] = round(prior_risk, 3)
                logger.debug(
                    "Multi-turn risk escalation: prior_risk=%.3f delta=%.3f", prior_risk, delta
                )
            # Intent continuity: carry forward the last detected intent as a hint
            prior_intent = turn_ctx.last_intent
            if prior_intent:
                context.metadata["prior_turn_intent"] = prior_intent
                logger.debug("Multi-turn intent continuity: prior_intent=%s", prior_intent)

            # Threat detection: analyze cross-turn patterns (fire-and-forget)
            import asyncio as _asyncio
            if turn_ctx.turns and context.session_id:
                try:
                    from aion.estixe.threat_detector import get_threat_detector
                    _td = _asyncio.create_task(
                        get_threat_detector().analyze(
                            context.tenant, context.session_id, turn_ctx.turns
                        )
                    )
                    from aion.pipeline import _BG_TASKS
                    _BG_TASKS.add(_td)
                    _td.add_done_callback(_BG_TASKS.discard)
                except Exception:
                    pass

        # P5: Scan all messages (system + historical user) before the last user message
        scan_block = await self._scan_all_messages(
            request.messages, pii_policy, context, threshold_overrides=threshold_overrides
        )
        if scan_block is not None:
            context.set_block(scan_block.block_reason or "Policy violation in message history")
            context.estixe_result = scan_block
            await self._velocity.record_block(context.tenant)
            return context

        # 0. PII guard on INPUT (current user message — not just output) — Track A1
        input_check = self._guardrails.check_output(user_message, pii_policy=pii_policy)

        if input_check.blocked:
            context.set_block(input_check.block_reason)
            context.metadata["pii_violations"] = input_check.violations
            result.action = EstixeAction.BLOCK
            result.pii_violations = input_check.violations
            result.block_reason = input_check.block_reason
            context.estixe_result = result
            await self._velocity.record_block(context.tenant)
            return context

        if not input_check.safe:
            logger.warning("PII detected in user input: %d violations", len(input_check.violations))
            context.metadata["pii_violations"] = input_check.violations
            result.pii_violations = input_check.violations
            if input_check.audited:
                context.metadata["pii_audited"] = input_check.audited
            # Sanitize input before proceeding (only if content was modified)
            if input_check.filtered_content != user_message:
                for msg in context.modified_request.messages:
                    if msg.role == "user" and msg.content == user_message:
                        msg.content = input_check.filtered_content
                        break
                user_message = input_check.filtered_content
                result.pii_sanitized = True

        # 1. Policy check — S1: regex/keyword signals (determinístico)
        policy_result = await self._policy.check(user_message, context)
        if policy_result.matched_rules:
            result.policy_matched = list(policy_result.matched_rules)
        if policy_result.blocked:
            context.set_block(policy_result.reason)
            result.action = EstixeAction.BLOCK
            result.policy_action = "block"
            result.block_reason = policy_result.reason
            context.estixe_result = result
            await self._velocity.record_block(context.tenant)
            self._tier_hits["policy"] += 1
            await self._cache_decision_if_safe(context, normalized, result)
            return context

        # 2. Transform input if policy says so
        if policy_result.transformed_input:
            result.policy_action = "transform"
            for msg in context.modified_request.messages:
                if msg.role == "user" and msg.content == user_message:
                    msg.content = policy_result.transformed_input
                    break

        # 3. S3: Structural risk classification — RiskClassifier (probabilístico)
        # threshold_overrides already resolved above (with velocity) — reuse here.
        # Executa ANTES do intent classifier para bloquear antes de consultar intents.yaml
        #
        # tenant_shadow_mode: override {"shadow_mode": true} via PUT /v1/overrides makes
        # ALL risk categories observe-only for this tenant — regardless of taxonomy config.
        # Useful for new clients where false-positive rate is still unknown.
        tenant_shadow_mode: bool = bool(context.metadata.get("shadow_mode"))
        if self._settings.risk_check_enabled:
            risk = self._risk_classifier.classify(user_message, threshold_overrides=threshold_overrides)
            if risk is not None:
                if risk.shadow or tenant_shadow_mode:
                    # Shadow mode: log observation, do NOT block — category is being evaluated
                    context.metadata["shadow_risk_category"] = risk.category
                    context.metadata["shadow_risk_level"] = risk.risk_level
                    context.metadata["shadow_risk_confidence"] = risk.confidence
                    context.metadata["shadow_risk_matched_seed"] = risk.matched_seed
                    logger.info(
                        "SHADOW OBSERVATION: category='%s' level='%s' conf=%.3f tenant_shadow=%s",
                        risk.category, risk.risk_level, risk.confidence, tenant_shadow_mode,
                    )
                    # Record to NEMOS for calibration (fire-and-forget)
                    import asyncio as _asyncio
                    try:
                        from aion.nemos import get_nemos
                        _asyncio.create_task(get_nemos().record_shadow_observation(
                            context.tenant, risk.category, risk.confidence
                        ))
                    except Exception:
                        pass
                elif risk.risk_level in ("critical", "high"):
                    block_reason = (
                        f"Solicitação bloqueada: risco estrutural "
                        f"'{risk.category}' detectado (confiança={risk.confidence:.2f})"
                    )
                    context.set_block(block_reason)
                    context.metadata["detected_risk_category"] = risk.category
                    context.metadata["risk_level"] = risk.risk_level
                    context.metadata["risk_confidence"] = risk.confidence
                    context.metadata["risk_matched_seed"] = risk.matched_seed
                    context.metadata["risk_threshold_used"] = risk.threshold_used
                    context.metadata["risk_source"] = "risk_classifier"
                    result.action = EstixeAction.BLOCK
                    result.policy_action = "block"
                    result.block_reason = block_reason
                    context.estixe_result = result
                    await self._velocity.record_block(context.tenant)
                    self._tier_hits["risk"] += 1
                    await self._cache_decision_if_safe(context, normalized, result)
                    return context
                elif risk.risk_level == "medium":
                    # FLAG apenas — continua pipeline, fica registrado nos metadados
                    context.metadata["flagged_risk_category"] = risk.category
                    context.metadata["flagged_risk_confidence"] = risk.confidence
                    context.metadata["flagged_risk_matched_seed"] = risk.matched_seed
                    context.metadata["flagged_risk_source"] = "risk_classifier"
                    logger.info(
                        "RISCO MÉDIO (flag, não bloqueia): '%s' conf=%.3f",
                        risk.category, risk.confidence,
                    )

        # 4. S4: Bypass check — SemanticClassifier (can we respond without LLM?)
        # NOTE: bypass_threshold is passed as parameter — never mutate the shared settings
        # singleton, which would cause race conditions under concurrent load.
        base_threshold = self._settings.bypass_threshold
        effective_threshold = await self._resolve_dynamic_threshold(context, base_threshold)

        bypass_result = await self._bypass.check(
            user_message, context,
            block_min_threshold=self._settings.block_min_threshold,
            bypass_threshold=effective_threshold,
            prior_intent=prior_intent,
        )

        if bypass_result.should_block:
            # Semantic block from intent classifier (action=block in intents.yaml)
            context.set_block(bypass_result.block_reason)
            context.metadata["detected_intent"] = bypass_result.intent
            context.metadata["intent_confidence"] = bypass_result.confidence
            result.action = EstixeAction.BLOCK
            result.policy_action = "block"
            result.block_reason = bypass_result.block_reason
            context.estixe_result = result
            await self._velocity.record_block(context.tenant)
            return context

        if bypass_result.should_bypass:
            context.set_bypass(bypass_result.response)
            context.metadata["detected_intent"] = bypass_result.intent
            context.metadata["intent_confidence"] = bypass_result.confidence
            result.action = EstixeAction.BYPASS
            result.intent_detected = bypass_result.intent
            result.intent_confidence = bypass_result.confidence
            if bypass_result.response and bypass_result.response.choices:
                result.bypass_response_text = bypass_result.response.choices[0].message.content
            context.estixe_result = result
            self._tier_hits["intent"] += 1
            # NOTA: BYPASS não pode ser cacheado via DecisionCache porque a response
            # é gerada on-demand (cada request precisa de um ChatCompletionResponse novo
            # com id/timestamp únicos). O SemanticClassifier já tem cache de embedding
            # que acelera o match; a resposta canned é dinâmica. Em v2 podemos cachear
            # o response template + injeter id/time por request.
            return context

        # CONTINUE path — still capture any detected intent
        if bypass_result.intent:
            result.intent_detected = bypass_result.intent
            result.intent_confidence = bypass_result.confidence
        context.estixe_result = result
        self._tier_hits["continue"] += 1
        # Cache decisão CONTINUE para próxima request idêntica
        await self._cache_decision_if_safe(context, normalized, result)
        return context

    # ──────────────────────────────────────────────
    # DecisionCache helpers
    # ──────────────────────────────────────────────

    async def _cache_decision_if_safe(self, context, normalized: str, result) -> None:
        """Armazena decisão (L1+L2) quando NÃO há sinais dinâmicos."""
        md = context.metadata
        if md.get("velocity_alert") or any(k.startswith("shadow_risk_") for k in md):
            return
        await self._decision_cache.put(context.tenant, normalized, result)

    async def check_llm_output(
        self, response_text: str, context: PipelineContext
    ) -> EstixeResult:
        """Verifica output do LLM por PII (S2') e risco estrutural (S3').

        Non-streaming apenas (v1) — streaming requer buffer de chunks, escopo v2.
        Dívida técnica: integrado via _pre_modules em main.py (v2 deve expor via interface).

        Delegated to OutputGuard — see aion/estixe/output_guard.py.
        """
        return await self._output_guard.check(response_text, context)

    async def _scan_all_messages(
        self,
        messages,
        pii_policy,
        context: PipelineContext,
        threshold_overrides: dict[str, float] | None = None,
    ) -> "EstixeResult | None":
        """Scan system and historical user messages for PII and policy violations.

        role:system   → PII + keyword policy + RiskClassifier (instruction injection via system é crítico)
        role:user histórico → PII apenas (evita falsos positivos contextuais)
        Última mensagem do usuário é excluída — verificada no fluxo normal.

        threshold_overrides: tenant overrides + velocity tightening from process() — ensures
        the same effective thresholds apply to system messages as to the current user input.

        Limitação deliberada v1: histórico do usuário não passa por RiskClassifier
        (apenas PII) para reduzir falsos positivos contextuais.
        """
        if not messages:
            return None

        system_msgs = [
            m for m in messages
            if getattr(m, "role", "") == "system" and getattr(m, "content", "")
        ]
        user_msgs = [
            m for m in messages
            if getattr(m, "role", "") == "user" and getattr(m, "content", "")
        ]
        # Exclude last user message — it's verified in the normal flow
        historical_user = user_msgs[:-1] if len(user_msgs) > 1 else []

        # System messages: PII + keyword policy + RiskClassifier (highest risk surface)
        for msg in system_msgs:
            text = str(msg.content)
            pii = self._guardrails.check_output(text, pii_policy=pii_policy)
            if pii.blocked:
                return self._make_block_result(pii.block_reason, pii_violations=pii.violations)
            pol = await self._policy.check(text, context)
            if pol.blocked:
                return self._make_block_result(pol.reason)
            # S3 on system messages — catches instruction injection with novel vocabulary.
            # Uses the same threshold_overrides as the main input scan (tenant + velocity).
            if self._settings.risk_check_enabled:
                risk = self._risk_classifier.classify(text, threshold_overrides=threshold_overrides)
                if risk is not None and not risk.shadow and risk.risk_level in ("critical", "high"):
                    return self._make_block_result(
                        f"Mensagem de sistema bloqueada: risco estrutural "
                        f"'{risk.category}' detectado (confiança={risk.confidence:.2f})"
                    )

        # Historical user messages: PII only (keyword policy may cause false positives on context)
        for msg in historical_user:
            pii = self._guardrails.check_output(str(msg.content), pii_policy=pii_policy)
            if pii.blocked:
                return self._make_block_result(pii.block_reason, pii_violations=pii.violations)

        return None

    @staticmethod
    def _make_block_result(
        reason: str, pii_violations: list[str] | None = None
    ) -> EstixeResult:
        """Build a BLOCK EstixeResult with optional PII violations."""
        r = EstixeResult(action=EstixeAction.BLOCK)
        r.block_reason = reason
        if pii_violations:
            r.pii_violations = pii_violations
        return r

    @staticmethod
    async def _resolve_dynamic_threshold(context: PipelineContext, default: float) -> float:
        """Adjust bypass threshold based on IntentMemory from NEMOS.

        - High bypass success → relax threshold (±0.05, min 0.70)
        - Low bypass success → tighten threshold (±0.05, max 0.95)
        - No NEMOS data → return default unchanged
        """
        try:
            from aion.nemos import get_nemos
            intent_mem = await get_nemos().get_intent_memory(context.tenant)
        except Exception:
            return default

        if not intent_mem:
            return default

        # Check overall bypass effectiveness across all intents
        total_seen = sum(m.total_seen for m in intent_mem.values())
        if total_seen < 20:
            return default  # not enough data

        total_bypass = sum(m.bypassed_count for m in intent_mem.values())
        if total_bypass == 0:
            return default

        # Weighted average bypass success rate across intents
        weighted_success = sum(
            m.bypass_success_rate.value * m.bypassed_count
            for m in intent_mem.values() if m.bypassed_count > 0
        )
        avg_success = weighted_success / total_bypass

        if avg_success > 0.95:
            # Bypass working well → relax slightly
            return max(0.70, default - 0.05)
        elif avg_success < 0.85:
            # Bypass failing → tighten
            return min(0.95, default + 0.05)

        return default

    @staticmethod
    def _resolve_pii_policy(context: PipelineContext) -> PiiPolicyConfig | None:
        """Resolve PII policy from context metadata (set by middleware/overrides).

        Precedence: request > override > tenant > default (None = mask all).
        """
        raw = context.metadata.get("pii_policy")
        if raw is None:
            return None
        if isinstance(raw, PiiPolicyConfig):
            return raw
        if isinstance(raw, dict):
            return PiiPolicyConfig(**raw)
        return None


_instance = None


def get_module() -> EstixeModule:
    global _instance
    if _instance is None:
        _instance = EstixeModule()
    return _instance
