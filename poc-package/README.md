# AION — POC Package

Pacote auto-contido para entrega a um cliente em POC. Inclui apenas o que
o operador precisa para colocar o stack de pé em ≤30 minutos. **Nada do
código-fonte do AION está aqui** — o image GHCR e o license JWT são
suficientes.

## Conteúdo

| Arquivo | Para quê |
|---|---|
| [`README.md`](README.md) | este arquivo (overview) |
| [`docker-compose.poc-decision.yml`](docker-compose.poc-decision.yml) | stack POC Decision-Only (recomendado) |
| [`docker-compose.poc-transparent.yml`](docker-compose.poc-transparent.yml) | stack POC Transparent (integração acelerada) |
| [`.env.poc-decision.example`](.env.poc-decision.example) | template de variáveis para POC Decision |
| [`.env.poc-transparent.example`](.env.poc-transparent.example) | template para POC Transparent |
| [`integration-guide.md`](integration-guide.md) | guia de integração da app do cliente com AION |
| [`smoke-test.sh`](smoke-test.sh) | smoke test pós-deploy (mesmo do `make verify-poc`) |
| [`postman_collection.json`](postman_collection.json) | requests prontos para Postman / Insomnia / Bruno |

## Setup em 3 passos

```bash
# 1) Variáveis de ambiente
cp .env.poc-decision.example .env
# Edite .env e preencha as 5 envs marcadas:
#   AION_LICENSE                  (JWT da Baluarte)
#   AION_ADMIN_KEY                (chave humana :admin)
#   AION_CONSOLE_PROXY_KEY        (openssl rand -hex 24)
#   AION_SESSION_AUDIT_SECRET     (openssl rand -hex 32)
#   CONSOLE_AUTH_SECRET           (openssl rand -hex 32)

# 2) Subir
docker compose -f docker-compose.poc-decision.yml up -d

# 3) Verificar
./smoke-test.sh decision http://localhost:8080
```

Esperado: todos os checks `[PASS]`, exit 0.

## Próximos passos depois do smoke OK

1. Importar `postman_collection.json` no Postman/Insomnia/Bruno.
2. Ler [`integration-guide.md`](integration-guide.md) para integrar a app
   do cliente com `POST /v1/decide` (Decision-Only) ou `POST /v1/chat/completions`
   (Transparent).
3. Acessar console em http://localhost:3000 (POC Decision) — login SSO
   conforme `.env` do console.

## Suporte

Para auditoria detalhada da postura de segurança, abrir
[`docs/SECURITY_REPORT.md`](../docs/SECURITY_REPORT.md) e
[`docs/PRODUCTION_CHECKLIST.md`](../docs/PRODUCTION_CHECKLIST.md) no
repositório principal. Contato técnico: contato@baluarte.ai.
