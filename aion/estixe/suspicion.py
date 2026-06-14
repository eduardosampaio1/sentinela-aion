"""Suspicion accumulator — surprise + momentum for slow-burn attack detection.

Pure math, no I/O. Inspired by the neural long-term memory of Titans
(arXiv 2501.00663): "memorizing = accumulating the gradient of prediction
error (surprise) with momentum and a forgetting gate."

Here each conversation turn contributes *surprise* (how far its risk exceeds an
expected baseline). Surprise accumulates with momentum (``eta``) into a single
decaying scalar that is persisted on the TurnContext. Because it is a scalar, it
survives the 3-turn sliding window and detects gradual probing that the strictly
increasing PROGRESSIVE_BYPASS check misses.

    S_t = eta * S_{t-1} + theta * max(0, risk_t - baseline)

This is the Fase-1 formulation: constant gates (eta, theta, baseline). Making
``eta`` data-dependent and the baseline NEMOS-learned is the documented P1.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SuspicionParams:
    """Constant gates for the suspicion accumulator.

    - ``eta``: momentum / forgetting carry. Must be a contraction (0 < eta < 1)
      so suspicion decays geometrically under calm turns.
    - ``theta``: learning rate applied to each turn's surprise.
    - ``baseline``: global fallback expected risk; only risk above it is surprising.
    - ``baselines``: per-category baselines (P1.2). The classifier has a high,
      category-varying benign floor, so each risk category gets its own baseline
      (seeded from risk_taxonomy benign_ceiling). Falls back to ``baseline``.
    """

    eta: float = 0.85
    theta: float = 1.0
    baseline: float = 0.30
    baselines: dict = field(default_factory=dict)
    # P1.3: {role: [categories]} — an authorized role makes those categories
    # non-surprising (legit admin asking for access is not an attack). Only
    # categories with a legitimate role (privilege/third_party); never
    # instruction_override/unsafe (those are never legitimate).
    role_authorizations: dict = field(default_factory=dict)


def baseline_for(category, params: SuspicionParams) -> float:
    """Per-category baseline if known, else the global fallback."""
    if category and category in params.baselines:
        return params.baselines[category]
    return params.baseline


def _authorized(category, roles, role_authorizations) -> bool:
    """True if any of ``roles`` legitimately accesses ``category``."""
    if not category or not roles:
        return False
    return any(category in role_authorizations.get(r, ()) for r in roles)


def role_authorized_for_block(category, roles, role_authorizations, enabled: bool) -> bool:
    """Whether a single-turn risk BLOCK should be bypassed for this role.

    SECURITY: gated by ``enabled`` (EstixeSettings.role_aware_block, default OFF) —
    relaxing a hard block is a deliberate opt-in, separate from the suspicion
    exemption. Only categories listed in ``role_authorizations`` (never
    instruction_override/unsafe) can be bypassed, and only for a backend-set role.
    """
    return bool(enabled) and _authorized(category, roles, role_authorizations)


def surprise(risk: float, baseline: float) -> float:
    """Positive surprise: how far ``risk`` exceeds ``baseline`` (never negative)."""
    return max(0.0, risk - baseline)


def update_suspicion(prev: float, risk: float, params: SuspicionParams, category=None, roles=None) -> float:
    """One accumulator step: decay the prior suspicion, add this turn's surprise.

    ``category`` selects the per-category baseline; None → global fallback.
    ``roles`` (P1.3): if the end-user's role legitimately accesses ``category``,
    the turn contributes zero surprise (legit privileged access ≠ attack).
    """
    if _authorized(category, roles, params.role_authorizations):
        eff_surprise = 0.0
    else:
        eff_surprise = surprise(risk, baseline_for(category, params))
    return params.eta * prev + params.theta * eff_surprise


def baselines_from_taxonomy(risk_definitions, margin: float = 0.0) -> dict:
    """Build the per-category baseline map from risk definitions' benign_ceiling."""
    return {r.name: r.benign_ceiling + margin for r in risk_definitions}


# Bounded transient tightening (Fase 2 enforcement). No ActuationGuard: the
# tightening is per-turn and relaxes automatically as suspicion decays via eta.
_ENFORCE_FLOOR = 0.55
_ENFORCE_MAX_DELTA = 0.15


def enforce_tightening(
    threshold_overrides,
    suspicion: float,
    enforce_threshold: float,
    risk_definitions,
):
    """Tighten risk thresholds when accumulated suspicion crosses the enforce bar.

    Returns ``threshold_overrides`` unchanged when ``suspicion`` is below
    ``enforce_threshold``. Otherwise builds overrides from the risk taxonomy
    (so it works even with no pre-existing overrides — mirrors velocity), lowers
    each by a bounded delta, and floors at 0.55. Only ever tightens (lowers).

    ``risk_definitions``: iterable of objects with ``.name`` and ``.threshold``.
    """
    if suspicion < enforce_threshold:
        return threshold_overrides

    over = suspicion - enforce_threshold
    delta = min(0.05 + over * 0.05, _ENFORCE_MAX_DELTA)
    base = threshold_overrides or {}
    return {
        r.name: max(_ENFORCE_FLOOR, base.get(r.name, r.threshold) - delta)
        for r in risk_definitions
    }
