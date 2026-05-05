# Fase 1 — Caça a Mentiras

Cada achado classificado por **categoria** + severidade.

---

## L-1 — MENTIRA DE DOCUMENTAÇÃO (CRÍTICA): "702+ testes"

- **Local da claim:** [docs/PRODUCTION_CHECKLIST.md:109,130](docs/PRODUCTION_CHECKLIST.md)
  - linha 109: `Rodar pytest tests/ em staging — **702+ testes, 0 falhas**`
  - linha 130: `| Test suite | ✅ 702 testes | pytest tests/ |`
- **Realidade:**
  ```
  $ grep -rch "^\(async \)\?def test_" tests/ | sum
  201
  ```
  **201 funções `def test_*` em todo o diretório `tests/`** (50 arquivos).
- **Discrepância:** declarada 702, real 201 → **inflação de ~250%** (3,5×).
- **Possível explicação benigna:** se cada teste é parametrizado com média 3,5 cases (`@pytest.mark.parametrize`), 201 × 3,5 ≈ 702. Mas isso seria "test cases", não "testes" — e a documentação não qualifica.
- **Severidade: S2.** Cliente que faz due-diligence e roda `pytest --collect-only | tail` espera ver ~700, vai ver muito menos. Isso queima credibilidade e levanta dúvida sobre o resto do checklist "✅ implementado".

---

## L-2 — MENTIRA DE DOCUMENTAÇÃO: `aion/rbac.py` não existe

- **Local da claim:** [docs/SECURITY_REPORT.md:36](docs/SECURITY_REPORT.md)
  > "RBAC implementado em `aion/rbac.py` com permissões granulares (override:read, override:write, etc)"
- **Realidade:** `ls aion/rbac.py` → "No such file or directory". RBAC vive em [aion/middleware.py](aion/middleware.py) + [aion/shared/contracts.py](aion/shared/contracts.py).
- **Severidade: S3.** Erro factual de documentação, mas RBAC de fato existe (em outro lugar).

---

## L-3 — MENTIRA DE DOCUMENTAÇÃO: `start.py` referenciado, não existe no repo

- **Local da claim:** [docs/SECURITY_REPORT.md:60](docs/SECURITY_REPORT.md)
  > "`start.py` tem guard-rail: em sim, força fake key para não vazar key real do dev"
- **Realidade:** não há `start.py` na raiz nem no pacote `aion/`. CLI é `aion/cli.py`.
- **Severidade: S3.** Doc desatualizado.

---

## L-4 — MENTIRA DE DOCUMENTAÇÃO: `AION_ADMIN_KEY` "comma-separated" sem mencionar formato `key:role`

- **Local da claim:** [docs/SECURITY_REPORT.md:33](docs/SECURITY_REPORT.md)
  > `AION_ADMIN_KEY` suporta rotação via comma-separated (`"key1,key2,key3"`)
- **Realidade:** [README.md:23](README.md), [aion/middleware.py:124-156](aion/middleware.py): formato é `key:role` (`"chave1:admin,chave2:operator"`). Sem `:role`, **legacy fallback default é ADMIN** ([aion/middleware.py:152-156](aion/middleware.py)) — formato antigo concede privilégio máximo silenciosamente.
- **Severidade: S2.** Documentação de segurança que omite o formato seguro pode levar operator a configurar `KEY1,KEY2` (legacy) e ganhar admin sem saber.

---

## L-5 — MENTIRA EXECUTIVA: `cost_saved_usd` resetado em todo restart

- **Local da claim:** [aion/routers/observability.py:283-291](aion/routers/observability.py) (`/v1/economics`)
  ```python
  return {
      "tenant": tenant,
      "economics": {
          "total_requests": total_requests,
          "llm_calls_avoided": bypasses,
          "tokens_saved": tokens_saved,
          "cost_saved_usd": cost_saved,  # ← counter in-memory
          ...
      },
  }
  ```
- **Implementação:** [aion/shared/telemetry.py:38](aion/shared/telemetry.py) — `_cost_saved_total: float = 0.0` é variável module-level **in-memory**.
- **Realidade:** counter zera em todo restart de pod. NEMOS persiste em Redis (em outra trilha), mas `/v1/economics` puxa o counter volátil.
- **Impacto:** Dashboard executivo mostra "economia desde sempre" que na verdade é "economia desde último deploy" — pode ser dias ou minutos. **Cliente vê US$ X reportados na segunda, US$ 0 reportados na terça após restart, e a história da economia "desaparece"**.
- **Severidade: S1.** Métrica executiva fabricada por dispositivo (volátil) — fere a 5ª Verdade (Prova Valor).

---

## L-6 — MENTIRA EXECUTIVA SUTIL: `total_spend_usd` mostra `cost_saved` como fallback quando não há histórico

- **Local:** [aion/routers/intelligence.py:108](aion/routers/intelligence.py)
  ```python
  "total_spend_usd": round(total_spend, 4) if total_spend else round(cost_saved, 4),
  ```
- **Realidade:** se `total_spend` (de NEMOS Redis) estiver vazio/zero, o campo "**total_spend_usd**" passa a exibir o valor de **economias** (`cost_saved`). Os dois conceitos são opostos!
- **Impacto:** Dashboard pode rotular o valor da economia como "gasto total". Possível leitura errada por executivo.
- **Severidade: S2.**

---

## L-7 — MENTIRA EXECUTIVA: `estimated_without_aion_usd` baseado em preços hardcoded

- **Local:** [aion/routers/intelligence.py:42-50](aion/routers/intelligence.py) + [config/models.yaml](config/models.yaml)
  - "estimativa do custo sem AION" usa `cost_per_1k_input/output` do YAML (`0.00015`, `0.0006` etc.).
- **Risco:** Se OpenAI/Anthropic mudam preços (já aconteceu várias vezes em 2024-2025), o cálculo de economia mostra resultado divergente do billing real do cliente.
- **Sem rastreabilidade da fonte:** o YAML não tem campo `pricing_source` nem `pricing_observed_at`. O cliente que perguntar "como você chegou nessa economia?" não vê fórmula auditável no produto.
- **Severidade: S2.**

---

## L-8 — MENTIRA FUNCIONAL POTENCIAL: `/v1/explain/{request_id}` só funciona enquanto está no buffer in-memory

- **Local:** [aion/routers/observability.py:424-447](aion/routers/observability.py)
  ```python
  events = get_recent_events(limit=1000, tenant=tenant)
  for event in events:
      if event.get("request_id") == request_id:
          return { ... }
  return {"request_id": request_id, "found": False, "message": "Request not found in recent events"}
  ```
- **Realidade:** "Explainability" só existe se o request ainda estiver na deque de 1.000 eventos da memória do processo (com `maxlen=10_000` no buffer global mas `limit=1000` no lookup). Em volume médio, isso some em minutos.
- **Promessa contradita:** README lista `/v1/explain/{request_id}` em **"Dados e Auditoria"** com descrição "Explicar decisao de um request especifico" — sem caveat. PRODUCTION_CHECKLIST claim "Audit log imutável" não cobre `/v1/explain` que é volátil.
- **Severidade: S1.** Em uma investigação real (incidente, dispute, regulador), o auditor espera reconstruir o request — vai cair em "Request not found".

---

## L-9 — MENTIRA DE INTEGRAÇÃO: telemetria forwarded para ARGOS contém `event.data["input"]` com texto da mensagem

- **Local:** [aion/shared/telemetry.py:124-142](aion/shared/telemetry.py)
  ```python
  def __init__(self, ..., input_text: str = "", metadata=None):
      self.data = {
          ...
          "input": input_text,  # texto da mensagem do usuário
          ...
          "metadata": _sanitize_metadata(metadata) if metadata else {},
      }
  ```
- **`_sanitize_metadata`** ([linha 87-89](aion/shared/telemetry.py)) só limpa o sub-dict `metadata`, **não toca em `input`**.
- **`emit()`** ([linha 190-197](aion/shared/telemetry.py)) faz `client.post(settings.argos_telemetry_url, json=event.data)` se `argos_telemetry_url` configurado.
- **Promessa contradita:**
  - [README.md:225-228](README.md):
    > "O que NUNCA sai: prompts, respostas, PII, dados de usuario."
  - [docs/ARCHITECTURE.md] e [PRODUCTION_CHECKLIST.md:84]: "PII não logado: verificar que `input_text` em eventos não contém PII não-redacted"
- **Realidade:** o campo `input` carrega a mensagem do usuário. Se ESTIXE rodou e detectou PII, **a mensagem ainda assim é gravada no buffer e enviada para ARGOS** (se opt-in for ligado). Não vi sanitização do `input` antes do `emit()` (apenas dentro de `metadata.pii_violations` o tipo é gravado).
- **Atenuante:** ARGOS é opt-in e desligado por default; Supabase só recebe metadata; deque é local. Mas a promessa "respostas/prompts NUNCA saem" depende da ausência de operadores ligando ARGOS — não é garantia técnica.
- **Severidade: S1.** Risco real e direto de PII leak via telemetria + `/v1/events`.

---

## L-10 — MENTIRA DE TESTE/DOC: "Distributed tracing (OTel)" — código existe mas é declarado "fora de escopo"

- **Claim 1:** [docs/PRODUCTION_CHECKLIST.md:46](docs/PRODUCTION_CHECKLIST.md):
  > "Distributed tracing (OpenTelemetry) — v2, hoje não está pronto"
- **Claim 2:** [docs/PRODUCTION_CHECKLIST.md:131](docs/PRODUCTION_CHECKLIST.md):
  > "Distributed tracing (OTel) | ❌ fora de escopo v1"
- **Realidade:** [aion/observability.py:25-66](aion/observability.py) (citação do Agent C) tem código `setup_telemetry(app)` que é chamado em [aion/main.py:163-166](aion/main.py).
- **Severidade: S3.** Inconsistência na documentação — o setup é opt-in via env, então "fora de escopo" é meio-verdade.

---

## L-11 — DEMO MENTIROSA POTENCIAL: `scripts/seed_sandbox.py` populando dashboards

- **Local:** [scripts/seed_sandbox.py](scripts/seed_sandbox.py) (não auditado em profundidade neste run)
- **Risco:** se `seed_sandbox.py` injetar eventos sintéticos no buffer/Redis, e for invocado em ambiente de demo/cliente, o dashboard mostra "economia" e "blocks" inventados. **Nada no script ou nas docs alerta para isso explicitamente.**
- **Severidade: S2** (RAD aceitável se houver ADR explícito declarando "ambiente sandbox usa seed; não usar em prod").

---

## L-12 — MENTIRA DE DEMO: `bypass_response` é template fixo do YAML

- **Local:** [aion/estixe/data/intents.yaml] (referenciado pelos agents) + [aion/routers/proxy.py:286-351](aion/routers/proxy.py)
- **Realidade:** quando ESTIXE faz `bypass`, retorna uma resposta fixa do YAML (ex: "Olá! Como posso ajudar?"). Isso **é por design** (zero-token cost saving), **não é mentira**.
- **Risco:** alguém pode interpretar "AION respondeu inteligentemente sem chamar LLM" como se fosse generative — mas é template. Se a documentação cliente-facing não deixar isso claro, vira mentira de demo.
- **Severidade: S3.** Aceitável se transparente.

---

## L-13 — MENTIRA DE DOCUMENTAÇÃO: "Zero CVEs em todas as dependências"

- **Local da claim:** [docs/SECURITY_REPORT.md:18-29](docs/SECURITY_REPORT.md)
  > "Zero CVEs em todas as dependências do AION"
- **Realidade:** dependências em `pyproject.toml` declaradas com `>=` (não pinned). pip-audit foi executado **uma vez** (em 2026-04-21 segundo o doc), em uma versão específica resolvida. Sem lockfile, qualquer instalação futura puxa versões diferentes que **podem ter CVEs**. O claim é verdadeiro **no momento do scan**, mas é tratado como permanente.
- **Severidade: S3.** Snapshot statement apresentado como fato perpetual.

---

## L-14 — MENTIRA DE TESTE POTENCIAL: tests usam `OPENAI_API_KEY="sk-test-key"` mas não auditam que o adapter realmente recusa quando a key é inválida

- **Local:** [tests/conftest.py:15] (citação do Agent C)
- **Risco:** todos os tests mockam a chamada upstream. **Nenhum teste hits real LLM**. Para a promessa "AION é proxy resiliente", existem testes do `proxy.py`, mas o ciclo "key inválida → upstream rejeita → fallback" só é validado contra mocks.
- **Severidade: S3.** Comum em testes; vale como gap de chaos engineering.

---

## L-15 — MENTIRA DE INFRAESTRUTURA: AION_LICENSE_SKIP_VALIDATION=true mata a proteção

- **Local:** [aion/license.py:235-245](aion/license.py)
  ```python
  if os.environ.get("AION_LICENSE_SKIP_VALIDATION", "").lower() == "true":
      logger.warning("AVISO: validação de licença desabilitada ...")
      _license_info = LicenseInfo(state=LicenseState.ACTIVE, tenant="dev", ...)
      return _license_info
  ```
- **Risco:** alguém esquecer essa env em prod = todo o sistema de licenciamento (Trust Guard, expiração, premium features) bypassed silenciosamente. Apenas log warning, nada mais.
- **Severidade: S2.** "Documentação para devs" deveria explicitar que essa flag NUNCA pode ir para imagem de produção. Idealmente, build de produção rejeita por design (compile-time check via build-arg).

---

## L-16 — MENTIRA DE LICENÇA: chave pública dev hardcoded como fallback

- **Local:** [aion/license.py:38-42](aion/license.py)
  ```python
  _EMBEDDED_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
  MCowBQYDK2VwAyEAhhHJu8ggP3+GFeVGYBc30RsNqzT4jkz3epGOmtfi/Oc=
  -----END PUBLIC KEY-----"""
  _PUBLIC_KEY_PEM = os.environ.get("AION_LICENSE_PUBLIC_KEY", _EMBEDDED_PUBLIC_KEY)
  ```
- **Promessa contradita:** ["Licença validada offline (Ed25519) — sem phone-home"](README.md) é fato; mas a integridade desse modelo depende de a chave pública estar trocada para a real em prod. Sem mecanismo que **force** essa troca (build-arg, segredo no GHA, validação de fingerprint conhecido), qualquer customer que esquecer a env aceita licenças assinadas com a chave dev — **e a chave privada dev existe localmente em mãos da Baluarte (e não está no repo, mas existe e é o pareamento da pública embutida)**.
- **Severidade: S1.** Cliente pen-tester pode demonstrar que `AION_LICENSE_PUBLIC_KEY` não setada + JWT assinado pela chave dev = AION inicia normal. Marca produção como "vulnerável a licença emitida fora do controle do cliente".

---

## Resumo

| ID | Categoria | Severidade |
|---|---|:---:|
| L-1 | DOCUMENTAÇÃO | S2 |
| L-2 | DOCUMENTAÇÃO | S3 |
| L-3 | DOCUMENTAÇÃO | S3 |
| L-4 | DOCUMENTAÇÃO | S2 |
| L-5 | EXECUTIVA | S1 |
| L-6 | EXECUTIVA | S2 |
| L-7 | EXECUTIVA | S2 |
| L-8 | FUNCIONAL | S1 |
| L-9 | INTEGRAÇÃO/PII | S1 |
| L-10 | DOCUMENTAÇÃO | S3 |
| L-11 | DEMO | S2 |
| L-12 | DEMO | S3 |
| L-13 | DOCUMENTAÇÃO | S3 |
| L-14 | TESTE | S3 |
| L-15 | INFRAESTRUTURA | S2 |
| L-16 | LICENÇA | S1 |

**Mentiras críticas que bloqueiam venda enterprise:** L-1, L-5, L-6, L-7, L-8, L-9, L-15, L-16.
