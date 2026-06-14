# Spec — Block single-turn role-aware (FP de admin legítimo)

**Data:** 2026-06-14 · **Branch:** `fix/estixe-ptbr-injection`
**Origem:** validação ao vivo do P1.3 mostrou que admin legítimo (privilege ~0.7) leva
**403 single-turn block** mesmo com `role=admin` — o block não é role-aware (só o acumulador era).

## Objetivo

Quando o end-user tem role que acessa legitimamente a categoria de risco, **não bloquear**
single-turn — registrar bypass auditável + continuar. Reduz FP de admin/support legítimos.

## Segurança (decidido)

Relaxar um block DURO é mais impactante que isentar suspeita. Gateado por flag dedicada
**`EstixeSettings.role_aware_block: bool = False`** (default OFF) — habilitar é decisão
deliberada e auditável, separada do `role_authorizations` (que governa o acumulador P1.3).
Trust = mesmo do P1.3: `X-Aion-User-Role` setado server-side pelo integrador.
instruction_override/unsafe/policy NUNCA entram em `role_authorizations` → nunca bypassáveis.

## Componentes

- `EstixeSettings.role_aware_block: bool = False`.
- `aion/estixe/suspicion.py`: helper puro `role_authorized_for_block(category, roles, role_auth, enabled) -> bool` = `enabled and _authorized(...)`. (reusa `_authorized`.)
- `aion/estixe/__init__.py`, branch `risk.risk_level in ("critical","high")`:
  - se `role_authorized_for_block(risk.category, metadata["user_roles"], get_role_authorizations(), settings.role_aware_block)` → grava `metadata["role_authorized_bypass"]={category,roles,confidence}` + `logger.info` (auditoria) + **continua** (sem set_block, sem return).
  - senão → block existente (inalterado).

## Testes (TDD)

- `role_authorized_for_block`: flag ON + role autoriza → True; **flag OFF + role autoriza → False** (contrato de segurança); role não autoriza → False; sem role → False.
- Verificação ao vivo (prod local): `role_aware_block=true` + `X-Aion-User-Role: admin` + pedido privilege → **NÃO 403** (continua), com `role_authorized_bypass` no metadata; sem role → 403.
- Suíte: default OFF → testes de block existentes inalterados (sem regressão).

## Fronteiras / YAGNI

- Só categorias em `role_authorizations` (privilege/third_party). 
- Não mexe no acumulador (P1.3) nem na política (stage 1).
- Bypass é auditado (metadata + log), não silencioso.
