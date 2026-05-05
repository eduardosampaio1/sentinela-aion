# Checklist Final

```
[x]  Escopo declarado (modo, limites, out-of-scope, promessas)        — scope.md
[x]  Tipo do projeto identificado                                      — Backend/AI service
[?]  Build validado                                                     — não rodado neste audit (read-only)
[?]  Typecheck/lint validados                                           — não rodado
[?]  Testes unitários validados                                         — não rodado; contagem real 201 funções
[?]  Testes de integração validados                                     — não rodado
[?]  Testes de contrato validados                                       — não rodado
[ ]  Fluxos principais ponta a ponta validados                          — chat/decision com gaps; explain com gap durabilidade
[ ]  Camadas compatíveis (cliente/produtor)                             — drift potencial console↔backend (sem schema compartilhado)
[x]  Sem mocks indevidos                                                — bypass_response é design transparente
[ ]  Sem dados fake em tela real                                        — cost_saved volátil + total_spend_usd fallback errado
[ ]  Sem dados fake em dashboard executivo                              — métricas executivas in-memory
[x]  Sem secrets expostos                                               — chave privada não no repo; só pública dev embutida (S1 separado)
[ ]  Sem vazamento entre boundaries de isolamento                       — RBAC ownership ausente
[ ]  Autenticação validada                                              — chat anônimo se ADMIN_KEY vazia
[ ]  Autorização validada                                               — RBAC por papel ok; ownership ausente
[ ]  Permissões testadas                                                — gaps específicos
[x]  Logs úteis e estruturados                                          — JSON ok
[ ]  Audit trail suficiente                                             — HMAC opcional → forjável
[x]  Erros tratados                                                     — circuit breaker, retries, fail-modes
[x]  Estados vazios tratados                                            — em geral
[x]  Timeouts tratados                                                  — httpx + stream timeout
[x]  Deploy reproduzível                                                — Docker + cosign + manifest
[ ]  Configuração de ambiente validada                                  — `_env_problems` warning, mas não bloqueia
[ ]  Documentação coerente com implementação                            — várias inconsistências (rbac.py, start.py, 702 testes)
[?]  AI/LLM: prompt injection mitigada (se aplicável)                   — parcial (semantic + policy)
[ ]  AI/LLM: output validado antes de persistir/exibir                  — METIS post optimizer scope incerto
[ ]  AI/LLM: eval suite presente                                        — testes existem; eval set adversarial estruturado ausente
[x]  AI/LLM: model fallback definido                                    — NOMOS chain
[ ]  AI/LLM: token budget capado                                        — diário/mensal sim; per-request não
[x]  Cost: hard cap em chamadas pagas                                   — diário/mensal
[ ]  Cost: alertas configurados com dono                                — `alert_threshold` existe; sem dono nomeado
[ ]  Cost: custo por unidade de valor medido                            — métrica volátil
[x]  Eventos críticos instrumentados                                    — sim
[x]  Eventos com identificador de boundary                              — sim (tenant)
[x]  Eventos com correlation_id                                         — sim (request_id)
[?]  Funil principal mensurável                                         — bypass success rate sim; ativação não
[~]  Métricas de produto definidas                                      — parcial
[ ]  Métricas de negócio definidas (uma por promessa)                   — várias promessas sem métrica
[ ]  ROI com fórmula rastreável (se prometido)                          — fórmula simples; insumos não rastreáveis (preços hardcoded)
[ ]  Dashboard com fonte real                                           — fonte real, mas volátil
[ ]  Recomendação com evidência (se aplicável)                          — `/v1/recommendations` existe; não mostra evidência subjacente
[ ]  RAD com 6 critérios em cada item                                   — zero RAD válidos atualmente
```

Legenda: `[x]` ok, `[ ]` falta/quebrado, `[?]` não validado neste audit, `[~]` parcial.
