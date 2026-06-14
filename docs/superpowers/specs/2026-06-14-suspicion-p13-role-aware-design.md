# Spec — P1.3: suspeita role-aware (identidade do end-user)

**Data:** 2026-06-14 · **Branch:** `fix/estixe-ptbr-injection`
**Origem:** P1.2b mostrou que privilege/fraude/acesso/social são score-indistinguíveis de
benigno legítimo. A diferença real é IDENTIDADE (quem pede), não o texto. Diversidade de
categoria NÃO separa (benigno espalha mais). Pivot: role-aware.

## Objetivo

Usar o role/identidade do end-user pra **decouplar "legítimo porque é admin" do score** —
permitindo BAIXAR os pisos (mais recall em ataque de não-privilegiado) e ISENTAR os
privilegiados legítimos (sem FP).

## Limite honesto (escopo)

Role separa **privilege_escalation** e **third_party_data_access** (têm role legítimo:
admin/support). **NÃO** separa fraud_enablement/social_engineering — o "reclamante de fraude"
é um user comum, mesmo role do atacante. Esses continuam no teto (P-futuro: identidade
fina, ex. "é o dono da conta"). instruction_override/unsafe nunca são legítimos (role-independent).

## Segurança (crítico)

Role chega via header **`X-Aion-User-Role`** setado **server-side pelo app integrador**
(que já autenticou o end-user). AION está on-prem atrás da auth do integrador.
**O integrador NUNCA repassa valor controlado pelo end-user** — senão `X-Aion-User-Role: admin`
vira bypass trivial. Documentar no runbook/integração. Default sem header = comportamento de hoje.

## Componentes

- **Config** `risk_taxonomy.yaml::role_authorizations` (default {}): `{admin: [privilege_escalation, third_party_data_access], support: [third_party_data_access]}`. Loader cacheado `get_role_authorizations()`.
- **Settings** `EstixeSettings.user_role_header: str = "X-Aion-User-Role"`.
- **Middleware/pipeline**: lê o header → `context.metadata["user_roles"]` (lista).
- **`aion/estixe/suspicion.py`**: `SuspicionParams += role_authorizations: dict`;
  `update_suspicion(prev, risk, params, category=None, roles=None)` → se `category ∈ authorized(roles)`, surpresa **0** (isento). Helper `_authorized(category, roles, role_auth)`.
- **`suspicion_eval`**: `CalibrationCase += roles: list`; `detect_turn`/`score_grid_point` aplicam isenção por role.
- **Pipeline turn-record**: passa `roles=context.metadata.get("user_roles")` ao `record_suspicion`.

## Recalibração

- Corpus `suspicion_realtext_corpus.yaml`: cada caso ganha `role` (benigno admin-legítimo → `admin`; demais benigno e TODOS os ataques → `user`/none).
- Scorer (`score_realtext_corpus.py`): carrega `role` pro YAML congelado.
- Calibração: pisos por-categoria recomputados do benigno **NÃO-isento** (turnos cujo role não autoriza a categoria) → pisos de privilege/third_party caem (o admin-legítimo sai do cálculo) → ataques (role user) passam a surpreender.
- Aplicar pisos novos; recalibrar η/θ/threshold; regressão (FP-zero + recall ≥ novo alvo, esperado > 0.40).

## Testes (TDD)

- `_authorized` / `update_suspicion` com roles: categoria autorizada → surpresa 0; não-autorizada → normal; sem role → normal (backward-compat).
- `detect_turn`/`score` com roles.
- Regressão: defaults + corpus role-tagged → FP-zero, recall recuperado; legit-admin (role admin) não dispara mesmo com piso baixo.
- Smoke: re-rodar.

## Fronteiras / YAGNI

- Só categorias com role legítimo (privilege/third_party). Fraude/social ficam no teto.
- Header trust = backend-set (não JWT; on-prem). Documentar.
- NÃO mexe no block single-turn (que também FPa em admin-legítimo) — **flag como item separado** (role-aware single-turn block é follow-up).
