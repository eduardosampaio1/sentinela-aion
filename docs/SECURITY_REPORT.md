# AION — Relatório de Segurança

Gerado em 2026-04-21. Última atualização: 2026-04-30 (correções de referências obsoletas).

## SAST — bandit
Varredura: `python -m bandit -r aion/ -ll`

| Severidade | Count |
|---|---|
| HIGH | **0** |
| MEDIUM | 1 |
| LOW | 21 |

**Medium issue único**: `host="0.0.0.0"` em `cli.py` — bind em todas as interfaces. Requerido em container (localhost do container ≠ localhost do host). Anotado como falso positivo.

**Low issues**: padrão em código Python (uso de `random.choice`, `try/except Exception`, etc). Nenhum representa vulnerabilidade real.

## Dependency audit — pip-audit
Executado dentro do container Docker AION:

```
$ docker exec aion python -m pip_audit
No known vulnerabilities found
```

**Zero CVEs** em todas as dependências do AION:
- fastapi, uvicorn, httpx, pydantic, pydantic-settings
- pyyaml, sentence-transformers, numpy, tiktoken
- redis, faiss-cpu, opentelemetry-*

## Auth & Access Control

- `AION_ADMIN_KEY` suporta rotação e roles via formato `"chave1:admin,chave2:operator,chave3:viewer"`
  - Roles válidas: `admin | operator | viewer | analyst | security | auditor | console_proxy`
  - Sem `:role` = legado, default ADMIN (deprecated; logar warning e exigir `:role` em produção)
- `AION_REQUIRE_CHAT_AUTH=true` força autenticação em `/v1/chat/completions`
- `AION_REQUIRE_TENANT=true` força header `X-Aion-Tenant` em todos os requests
- RBAC implementado em [aion/middleware.py](aion/middleware.py) (parsing + enforcement) e
  [aion/shared/contracts.py](aion/shared/contracts.py) (`Role`, `Permission`, matriz de permissões).
  Não existe um arquivo `aion/rbac.py` separado — toda a lógica RBAC vive nos dois arquivos acima.
- **F-37**: quando `AION_MODE=poc_decision` ou `decision_only`, `/v1/chat/completions` e
  `/v1/chat/assisted` retornam **403** mesmo se autenticados — Decision-Only é enforçado em runtime.
- **AION_PROFILE=production** (gating de produção): boot aborta se faltar
  `AION_SESSION_AUDIT_SECRET`, `AION_LICENSE_PUBLIC_KEY`, `AION_ADMIN_KEY`
  (com `:role`), ou se houver credencial LLM em env quando `AION_MODE` é Decision-Only.

## CORS

- Configurado via `AION_CORS_ORIGINS` (comma-separated). Sem default.
- Em dev: `http://localhost:3000,http://localhost:3001`
- Em prod: apenas origens do cliente. Nunca `*`.

## Rate limiting

- Per `tenant + IP` via Redis sorted set sliding window
- Fallback in-memory quando Redis down
- Configurável por endpoint (chat vs admin)

## Isolamento de tenants

- Rota estruturada por header `X-Aion-Tenant`
- Overrides, rate limits, velocity, events: chaves Redis prefixadas `aion:*:{tenant}:*`
- Sem API que cross-tenant sem admin privilege

## Secrets

- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`: via env var, never logged.
- `AION_ADMIN_KEY`: via env var. Comparação atual via dict lookup
  ([aion/middleware.py](aion/middleware.py)); roadmap (S3): trocar por `hmac.compare_digest`
  para garantir constant-time bit-a-bit.
- Entrypoint do binário é [aion/cli.py](aion/cli.py) (instalado como `aion` via
  `pyproject.toml [project.scripts]`). **Não existe `start.py`.**
- Em testes ([tests/conftest.py](tests/conftest.py)) `OPENAI_API_KEY=sk-test-key` é
  setada explicitamente — guard contra vazamento de key real do dev.

## Container hardening

- User não-root (uid=1000)
- Base image slim + apenas deps mínimas
- Healthcheck + readiness probe
- Memory + CPU limits via docker-compose
- `HF_HUB_OFFLINE=1` — sem calls externos em runtime

## Recomendações para produção

- [ ] Rodar `bandit` no CI (já implementado em FASE 6)
- [ ] Rodar `pip-audit` semanalmente no CI
- [ ] Rotar `AION_ADMIN_KEY` a cada 30-90 dias
- [ ] Certificado TLS terminator na frente (nginx + Let's Encrypt)
- [ ] Scan OWASP ZAP dinâmico antes de cada release
- [ ] Pen test profissional antes de GA multi-cliente
