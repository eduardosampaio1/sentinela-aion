"""License validation for AION.

Offline-validatable signed license using EdDSA (Ed25519) JWT.

States
------
INVALID  → AION refuses to start. Explicit error, no ambiguity.
ACTIVE   → All features enabled.
GRACE    → All features enabled + warnings (7-day window after expiry).
EXPIRED  → fail-open: CONTINUE always; BLOCK/PII maintained; premium features disabled.

The private key never leaves the licensor. Only the public key is embedded here.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aion.license")

# ── Algorithm ──────────────────────────────────────────────────────────────────
# Fixed. Any other algorithm is rejected unconditionally.
_ALGORITHM = "EdDSA"

# ── Grace period ───────────────────────────────────────────────────────────────
_GRACE_SECONDS = 7 * 24 * 3600  # 7 days

# ── Public key (embedded — DEV/TEST ONLY) ─────────────────────────────────────
# F-04: this key is the dev/test pair (private key in tools/keys/ — never committed).
# It is INTENTIONALLY published in source so the dev workflow stays simple.
# Production deployments MUST override via AION_LICENSE_PUBLIC_KEY env var.
# When AION_PROFILE=production, validate_license_or_abort() refuses to fall back
# to this embedded key.
_EMBEDDED_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAhhHJu8ggP3+GFeVGYBc30RsNqzT4jkz3epGOmtfi/Oc=
-----END PUBLIC KEY-----"""

# Sentinel marker so we can tell at runtime whether the embedded fallback is in use.
_EMBEDDED_PUBLIC_KEY_FINGERPRINT = "dev-only-MCowBQYDK2VwAyEAhhHJu8gg"

_PUBLIC_KEY_PEM = os.environ.get("AION_LICENSE_PUBLIC_KEY", _EMBEDDED_PUBLIC_KEY)


def _is_using_embedded_dev_key() -> bool:
    """Return True if the active public key is the embedded dev/test key."""
    return _PUBLIC_KEY_PEM.strip() == _EMBEDDED_PUBLIC_KEY.strip()

# ── Env var / file path ────────────────────────────────────────────────────────
_LICENSE_ENV_VAR = "AION_LICENSE"          # inline JWT string
_LICENSE_PATH_VAR = "AION_LICENSE_PATH"    # path to .lic file


class LicenseState(str, Enum):
    ACTIVE  = "active"
    GRACE   = "grace"
    EXPIRED = "expired"
    INVALID = "invalid"


# Features that are disabled when EXPIRED
_PREMIUM_FEATURES = {"nomos", "metis_advanced", "analytics", "multi_tenant"}


@dataclass
class LicenseInfo:
    state: LicenseState
    tenant: str = ""
    issued_to: str = ""
    features: list[str] = field(default_factory=list)
    tier: str = ""
    env: str = ""
    expires_at: float = 0.0
    days_remaining: float = 0.0
    error: str = ""

    @property
    def is_operational(self) -> bool:
        """True if AION should start and serve traffic."""
        return self.state != LicenseState.INVALID

    def feature_enabled(self, feature: str) -> bool:
        """Check if a feature is available under current license state."""
        if self.state == LicenseState.INVALID:
            return False
        if self.state == LicenseState.EXPIRED:
            # Premium features disabled on expiry — fail-open for core traffic
            return feature not in _PREMIUM_FEATURES
        # ACTIVE or GRACE: check claims
        if not self.features:
            return True  # no restriction in claims = all features allowed
        return feature in self.features


# ── Singleton ──────────────────────────────────────────────────────────────────
_license_info: Optional[LicenseInfo] = None

# Raw JWT claims — made available to Trust Guard for optional extended claims
# (license_id, heartbeat_url, heartbeat_required, min_aion_version, etc.)
# Populated by _validate_token(); empty dict when dev-bypass is active.
_raw_claims: dict = {}


def get_license() -> LicenseInfo:
    """Return the current license state. Call after validate_license_or_abort()."""
    global _license_info
    if _license_info is None:
        _license_info = LicenseInfo(state=LicenseState.INVALID, error="license not loaded")
    return _license_info


# ── Loading ────────────────────────────────────────────────────────────────────

def _load_token() -> Optional[str]:
    """Load JWT token from env var or file. Returns None if not configured."""
    token = os.environ.get(_LICENSE_ENV_VAR, "").strip()
    if token:
        return token

    path_str = os.environ.get(_LICENSE_PATH_VAR, "").strip()
    if path_str:
        path = Path(path_str)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip()

    # Fallback: look for aion.lic next to the running module
    default_path = Path(__file__).resolve().parent.parent / "aion.lic"
    if default_path.exists():
        return default_path.read_text(encoding="utf-8").strip()

    return None


# ── Validation ─────────────────────────────────────────────────────────────────

def _validate_token(token: str, public_key_pem: str) -> LicenseInfo:
    """Validate JWT token. Returns LicenseInfo with state set appropriately."""
    try:
        import jwt as pyjwt
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError as e:
        return LicenseInfo(
            state=LicenseState.INVALID,
            error=f"Missing dependency: {e}. Install with: pip install PyJWT cryptography",
        )

    # Step 1: decode header without verification to check algorithm
    try:
        header = pyjwt.get_unverified_header(token)
    except Exception:
        return LicenseInfo(state=LicenseState.INVALID, error="algoritmo inválido: token malformado")

    if header.get("alg") != _ALGORITHM:
        return LicenseInfo(
            state=LicenseState.INVALID,
            error=f"algoritmo inválido: esperado {_ALGORITHM!r}, recebido {header.get('alg')!r}",
        )

    # Step 2: load public key
    try:
        pub_key = load_pem_public_key(public_key_pem.encode())
    except Exception as e:
        return LicenseInfo(state=LicenseState.INVALID, error=f"chave pública inválida: {e}")

    # Step 3: verify signature + decode claims (skip exp — we handle it manually)
    try:
        claims = pyjwt.decode(
            token,
            pub_key,
            algorithms=[_ALGORITHM],
            options={"verify_exp": False},  # manual expiry for grace period
        )
    except pyjwt.InvalidSignatureError:
        return LicenseInfo(state=LicenseState.INVALID, error="assinatura inválida")
    except pyjwt.DecodeError as e:
        return LicenseInfo(state=LicenseState.INVALID, error=f"token malformado: {e}")
    except Exception as e:
        return LicenseInfo(state=LicenseState.INVALID, error=f"erro de validação: {e}")

    # Save raw claims for Trust Guard extended fields (license_id, heartbeat_url, etc.)
    global _raw_claims
    _raw_claims = claims

    # Step 4: validate required claims
    tenant = claims.get("sub", "").strip()
    if not tenant:
        return LicenseInfo(state=LicenseState.INVALID, error="claim 'sub' ausente ou vazio")

    exp = claims.get("exp")
    if exp is None:
        return LicenseInfo(state=LicenseState.INVALID, error="claim 'exp' ausente")

    iat = claims.get("iat")
    nbf = claims.get("nbf", iat)
    now = time.time()

    if nbf and now < nbf:
        return LicenseInfo(
            state=LicenseState.INVALID,
            error=f"licença ainda não é válida (nbf={nbf}, agora={now:.0f})",
        )

    # Step 5: calculate state
    days_remaining = (exp - now) / 86400

    if now <= exp:
        state = LicenseState.ACTIVE
    elif now <= exp + _GRACE_SECONDS:
        state = LicenseState.GRACE
        days_remaining = (exp + _GRACE_SECONDS - now) / 86400
    else:
        state = LicenseState.EXPIRED
        days_remaining = 0.0

    return LicenseInfo(
        state=state,
        tenant=tenant,
        issued_to=claims.get("issued_to", tenant),
        features=claims.get("features", []),
        tier=claims.get("tier", "standard"),
        env=claims.get("env", "prod"),
        expires_at=float(exp),
        days_remaining=max(0.0, days_remaining),
    )


# ── Boot validation ────────────────────────────────────────────────────────────

def validate_license_or_abort() -> LicenseInfo:
    """Validate license at boot. INVALID = print explicit error + sys.exit(1).

    Called once from main.py lifespan. Result is cached in module singleton.
    """
    global _license_info

    public_key_pem = _PUBLIC_KEY_PEM.strip()

    # F-04 + F-05: in production profile, refuse the dev key fallback and
    # refuse the SKIP_VALIDATION shortcut. Both must come from env so the
    # deployment is auditable.
    try:
        from aion.config import Profile, get_settings
        _profile = get_settings().profile
    except Exception:
        _profile = None  # config unavailable → behave as development

    # Dev mode bypass: AION_LICENSE_SKIP_VALIDATION=true (dev/test only)
    if os.environ.get("AION_LICENSE_SKIP_VALIDATION", "").lower() == "true":
        if _profile == Profile.PRODUCTION:
            _abort(
                "AION_LICENSE_SKIP_VALIDATION=true em produção",
                "Esta variável só pode ser usada em AION_PROFILE=development.\n"
                "Remova AION_LICENSE_SKIP_VALIDATION ou ajuste AION_PROFILE.",
            )
        logger.warning("AVISO: validação de licença desabilitada (AION_LICENSE_SKIP_VALIDATION=true)")
        _license_info = LicenseInfo(
            state=LicenseState.ACTIVE,
            tenant="dev",
            issued_to="Development",
            features=[],
            tier="dev",
            env="dev",
        )
        return _license_info

    if not public_key_pem:
        _abort("chave pública não configurada",
               "Defina AION_LICENSE_PUBLIC_KEY com a chave pública Ed25519.")

    # F-04: refuse to start in production with the embedded dev public key.
    if _profile == Profile.PRODUCTION and _is_using_embedded_dev_key():
        _abort(
            "chave pública DEV em produção",
            "AION_LICENSE_PUBLIC_KEY não está definida — o fallback embutido\n"
            "é a chave de desenvolvimento. Em AION_PROFILE=production, defina\n"
            "AION_LICENSE_PUBLIC_KEY com a chave Ed25519 oficial da Baluarte.",
        )

    token = _load_token()

    if not token:
        _abort(
            "licença ausente",
            f"Nenhuma licença encontrada. Configure via:\n"
            f"  {_LICENSE_ENV_VAR}=<jwt>               (variável de ambiente)\n"
            f"  {_LICENSE_PATH_VAR}=/caminho/aion.lic  (arquivo)\n"
            f"  aion.lic                               (na raiz do projeto)",
        )

    info = _validate_token(token, public_key_pem)

    if info.state == LicenseState.INVALID:
        _abort(info.error)

    _license_info = info
    _log_license_state(info)
    return info


def _abort(reason: str, hint: str = "") -> None:
    """Print explicit error banner and exit. Never silently fails."""
    lines = [
        "",
        "  ╔══════════════════════════════════════════════════════╗",
        "  ║              AION — LICENÇA INVÁLIDA                 ║",
        "  ╠══════════════════════════════════════════════════════╣",
        f"  ║  Motivo : {reason:<44} ║",
    ]
    if hint:
        for hline in hint.splitlines():
            lines.append(f"  ║  {hline:<52} ║")
    lines += [
        "  ╠══════════════════════════════════════════════════════╣",
        "  ║  O AION não pode iniciar sem licença válida.         ║",
        "  ║  Contato: contato@baluarte.ai                        ║",
        "  ╚══════════════════════════════════════════════════════╝",
        "",
    ]
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(1)


def _log_license_state(info: LicenseInfo) -> None:
    if info.state == LicenseState.ACTIVE:
        logger.info(
            "Licença ATIVA | tenant=%s | issued_to=%s | tier=%s | expira em %.0f dias",
            info.tenant, info.issued_to, info.tier, info.days_remaining,
        )
    elif info.state == LicenseState.GRACE:
        logger.warning(
            "LICENÇA EM GRACE PERIOD | tenant=%s | %.0f dias restantes para renovação",
            info.tenant, info.days_remaining,
        )
    elif info.state == LicenseState.EXPIRED:
        logger.warning(
            "LICENÇA EXPIRADA | tenant=%s | modo degradado ativo (CONTINUE sempre disponível)",
            info.tenant,
        )
