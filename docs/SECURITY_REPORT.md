# AION — Relatório de Segurança

Gerado em 2026-04-21.

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

- `AION_ADMIN_KEY` suporta rotação via comma-separated (`"key1,key2,key3"`)
- `AION_REQUIRE_CHAT_AUTH=true` força autenticação em `/v1/chat/completions`
- `AION_REQUIRE_TENANT=true` força header `X-Aion-Tenant` em todos os requests
- RBAC implementado em `aion/rbac.py` com permissões granulares (override:read, override:write, etc)

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

- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`: via env var, never logged
- `AION_ADMIN_KEY`: via env var, comparação constant-time
- `start.py` tem guard-rail: em sim, força fake key para não vazar key real do dev

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
