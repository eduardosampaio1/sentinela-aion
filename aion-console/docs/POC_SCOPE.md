# AION — Linha de Corte Oficial da POC

> **POC não é o AION completo. POC é o menor AION capaz de provar decisão, economia, risco e auditabilidade.**

Documento de referência para escopo da POC. Define o que entra, o que fica fora e o que vem depois. Qualquer feature não listada como obrigatória ou desejável está fora da POC.

---

## 1. Definição oficial

A POC recomendada é **Decision-Only**.

```
App do cliente
  → AION /v1/decide
  → Decision Contract
  → App do cliente executa LLM/API com suas próprias credenciais
```

Na POC:

- AION **não recebe** chave de LLM do cliente
- AION **não executa** chamadas ao LLM do cliente
- AION **não envia** telemetria externa para a Baluarte
- AION **não usa** Supabase da Baluarte
- AION **não depende** de endpoint Render da Baluarte
- Redis é **local / do cliente**
- Foco: provar decisão, segurança, economia, risco e auditabilidade

**POC Transparent** existe como alternativa acelerada para clientes que não querem alterar código de integração (trocam só `base_url`). Não é o modo padrão — aumenta a superfície porque o AION recebe a chave de LLM.

### Frase comercial oficial

> Na POC, o AION roda dentro da arquitetura do cliente em modo Decision-Only. Ele avalia requisições, retorna decisões auditáveis e permite medir risco, bypass e economia estimada sem receber chave da LLM, sem executar chamadas externas e sem enviar dados para a Baluarte.

---

## 2. Tabela executiva

| Item / Capacidade | Vai para POC? | Motivo | Como demonstrar valor | Fica para quando? |
|---|---|---|---|---|
| AION Runtime | ✅ Obrigatório | É o produto. Sem ele não há POC. | Container respondendo, uptime visível no console | POC |
| Docker POC Decision-Only | ✅ Obrigatório | Remove fricção de deploy. Quickstart ≤ 5 min. | `docker compose up` — 3 comandos, está up | POC |
| `/v1/decide` | ✅ Obrigatório | Único endpoint que a POC expõe. | Curl devolvendo Decision Contract ao vivo | POC |
| Decision Contract | ✅ Obrigatório | Contrato que o cliente lê e age — `decision`, `model_hint`, `policy_applied`, `cost_saved_estimate`, `reason` | JSON mostrado no console por request | POC |
| ESTIXE básico | ✅ Obrigatório | Principal argumento de economia (bypass) e segurança (block). | Bypass rate visível no console em tempo real | POC |
| bypass | ✅ Obrigatório | Prova economia imediata. Primeira pergunta do CTO. | Console: custo estimado evitado acumulando ao vivo | POC |
| prompt injection block | ✅ Obrigatório | Prova segurança em 30 segundos. Demonstrável sem preparação. | Digitar "ignore previous instructions" → console registra `block` com razão | POC |
| PII detection | ✅ Obrigatório | Argumento LGPD/jurídico. CISO exige antes de assinar. Prometer **detecção**, não redação. | Enviar CPF no prompt → Decision Contract mostra `pii_detected: ["CPF"]` | POC |
| NOMOS rule-based | ✅ Obrigatório | Decision Contract precisa incluir `model_hint`. Sem isso o contrato é incompleto. | `model_hint: gpt-4o-mini` com razão de classificação | POC |
| NEMOS local | ✅ Obrigatório | Motor de classificação do ESTIXE. Roda on-premise, zero callout externo. | Transparente para o cliente | POC |
| Redis local / do cliente | ✅ Obrigatório | State store sob controle do cliente. Argumento de soberania. | "Todo dado fica no seu ambiente" | POC |
| Console de leitura real | ✅ Obrigatório | **Produto, não espetáculo.** Produto, FinOps, Segurança e liderança não leem log cru. Sem console a POC é caixa preta. | Console respondendo as 11 perguntas obrigatórias | POC |
| status/health real | ✅ Obrigatório | Pergunta 1: "O AION está rodando?" Visível sem abrir terminal. | Badge on/off com uptime no header do console | POC |
| modo atual visível | ✅ Obrigatório | Perguntas 2 e 3: qual modo, telemetria está ligada? Confiança imediata do CISO. | Pill no console: `Decision-Only · Telemetria: OFF · Collective: inativo` | POC |
| painel de decisões | ✅ Obrigatório | Perguntas 5, 6, 7, 8: quantas decisões, bypasses, bloqueios e por quê. | Página de Operação com filtros, decisão, razão e módulo por request | POC |
| audit trail legível | ✅ Obrigatório | Pergunta 10: "Onde está o audit?" O CISO precisa ver sem pedir ao engenheiro. | Lista de decisões com timestamp, hash, razão — não só JSONL em disco | POC |
| resumo de economia/risco | ✅ Obrigatório | Pergunta 9: "Quanto economizou?" FinOps precisa desse número para justificar renovação. | Card com `total_bypassed`, `cost_saved_estimate`, `blocks` por categoria | POC |
| export CSV/JSON simples | ✅ Obrigatório | Pergunta 11: "Dá para exportar evidência?" Compliance e FinOps pedem na primeira semana. | Botão no console → download do audit filtrado por período | POC |
| documentação POC vs Shadow vs Full | ✅ Obrigatório | Remove objeção de "e depois?" na demo. Cliente precisa ver onde está e para onde vai. | README + roteiro de adoção de 3 fases visível no console | POC |
| quickstart funcionando | ✅ Obrigatório | A POC não pode falhar no primeiro passo do cliente. Testado em máquina sem histórico Baluarte. | 5 minutos do zero ao primeiro `/v1/decide` | POC |
| zero callouts externos verificável | ✅ Obrigatório | Deve ser verificável, não só prometido. | Indicador de telemetria OFF no console + modo Decision-Only visível | POC |
| POC Transparent | 🟡 Desejável | Alternativa para cliente sem alteração de código. Não é padrão — requer chave LLM. | Documentado como modo alternativo | POC (alternativo) |
| relatório local de economia | 🟡 Desejável | Console já mostra resumo. Relatório exportável formal ajuda na renovação. | Gerado a partir das decisões existentes | POC (não bloqueante) |
| demo script com cenários prontos | 🟡 Desejável | Reduz risco de demo ao vivo. Garante que o operador mostra os casos certos. | Curl scripts: bypass · block · PII · route | POC (não bloqueante) |
| health/ready visual enriquecido | 🟡 Desejável | O mínimo (badge on/off) já é obrigatório. Latência p95, memória são desejáveis. | Painel de infra no console | Pós-POC / v1.1 |
| export SIEM avançado | 🟡 Desejável | Se o export básico já está no console, este item é redundante. | `GET /v1/audit?format=csv` com campos específicos de SIEM | Pós-POC |
| PII redaction | ⚠️ Condicional | Só entra na POC se implementada, testada e confiável. Prometer redaction sem garantia é risco jurídico para a Baluarte e para o cliente. | Fora até estar validada | Pós-POC / v1.1 |
| installed policies estáticas | ⚠️ Não destacar | Sem lifecycle honesto parece marketplace fake. Pode existir internamente mas não é destaque de POC. | Se aparecer, rotular como "catálogo editorial" | Collective Phase 0 |
| METIS | ❌ Fora | Compressão de contexto requer `/v1/complete`. Fora do fluxo Decision-Only por definição. | — | Full Decision-Only |
| NOMOS ML adaptativo | ❌ Fora | Roteamento baseado em embedding e histórico. Rule-based cobre a POC. | — | Full / Shadow |
| Shadow Mode | ❌ Fora | Fase de adoção, não feature da POC. Vira oferta do contrato pós-POC. | — | Fase 2 pós-POC |
| telemetria externa | ❌ Fora | Principal objeção de CISO e jurídico. Zero opt-in na POC. | — | Full, opt-in explícito |
| Supabase Baluarte | ❌ Fora | Dependência externa. Proibida na POC por design. | — | Nunca na POC |
| Render endpoint Baluarte | ❌ Fora | Idem. | — | Nunca na POC |
| Collective Phase 0 (inteligência real) | ❌ Fora | Requer múltiplos tenants. POC é single-tenant isolado. Se aparecer no console, rotular como catálogo editorial sem runtime enforcement. | — | Collective |
| runtime enforcement de Collective policies | ❌ Fora (salvo se já implementado) | Não prometer o que não está feito. | — | Collective |
| NEMOS Collective | ❌ Fora | Requer dados de múltiplos tenants. | — | Collective |
| cross-tenant intelligence | ❌ Fora | Proibido na POC por soberania de dados. | — | Collective opt-in |
| k-anonymity | ❌ Fora | Técnica para dados coletivos. Sem Collective não faz sentido. | — | Collective |
| benchmark setorial | ❌ Fora | Requer base comparativa de Collective. | — | Collective |
| AION Cloud Plane | ❌ Fora | SaaS managed. POC é on-premise. | — | Oferta separada |
| DPA Collective | ❌ Fora | Contrato jurídico de dados coletivos. | — | Collective |
| policy scoring global | ❌ Fora | Requer histórico mínimo de 30 dias + Collective. | — | Full |
| Emergency Threat Channel | ❌ Fora | Inteligência coletiva em tempo real. | — | Collective |
| Private Exchange | ❌ Fora | Feature enterprise entre organizações. | — | Collective |
| success fee automático | ❌ Fora | Modelo comercial, não feature técnica. | — | Contrato Full |
| SSO/RBAC corporativo | ❌ Fora | Overkill para POC. API key resolve. | — | Full enterprise |
| approval workflow | ❌ Fora | Governança de mudanças de política. Irrelevante na POC. | — | Full |
| SIEM/export avançado | ❌ Fora (exportbasico cobre) | Export básico do console cobre o escopo da POC. | — | Full enterprise |
| marketplace / community policies | ❌ Fora | Depende de Collective. | — | Collective |
| Full Transparent | ❌ Fora | AION como proxy completo com chave LLM do cliente. Aumenta superfície e objeção. | — | Fase 3+ |
| Full Decision-Only | ❌ Fora | Evolução com NOMOS ML, METIS, Collective. | — | Fase 2 pós-POC |

---

## 3. Obrigatório para POC

- AION Runtime
- Docker POC Decision-Only (quickstart ≤ 5 min em máquina limpa)
- `/v1/decide` com Decision Contract completo
- ESTIXE básico (bypass + block)
- bypass
- prompt injection block
- PII detection — **não redaction**
- NOMOS rule-based (`model_hint` no contrato)
- NEMOS local (motor de classificação on-premise)
- Redis local / do cliente
- **Console de leitura real é obrigatório, não demo visual** — deve responder as 11 perguntas
- status/health real visível no console
- modo atual visível (`Decision-Only · Telemetria: OFF · Collective: inativo`)
- painel de decisões com filtros
- audit trail legível no console
- resumo de economia/risco estimado
- export CSV/JSON simples
- documentação clara separando POC / Shadow / Full
- quickstart funcionando em ambiente limpo
- zero callouts externos verificável

---

## 4. Desejável, mas não bloqueante

1. **POC Transparent** — modo alternativo para cliente sem alteração de código de integração
2. **Relatório local de economia** — complementa o resumo do console
3. **Demo script com cenários prontos** — curl scripts para bypass, block, PII, route
4. **Export SIEM em formato específico** — só se o cliente exigir além do CSV padrão
5. **Health/ready visual enriquecido** — latência p95, memória, threads além do badge on/off

---

## 5. Não levar para POC de jeito nenhum

- Telemetria externa de qualquer tipo
- Supabase / Render da Baluarte
- NEMOS Collective real
- cross-tenant intelligence
- k-anonymity
- benchmark setorial
- AION Cloud Plane
- DPA Collective completo
- policy scoring global
- Emergency Threat Channel / Private Exchange
- success fee automático
- SSO/RBAC corporativo
- approval workflow
- runtime enforcement de Collective policies (se não implementado e testado)
- marketplace / community policies
- PII redaction (se não implementada e testada)
- installed policies YAML sem lifecycle honesto — não destacar como feature
- Collective Phase 0 rotulado como inteligência coletiva real (se for só catálogo editorial)
- NOMOS ML adaptativo
- METIS
- Shadow Mode
- Full Transparent / Full Decision-Only

---

## 6. Console: as 11 perguntas obrigatórias

O console da POC precisa responder, sem abrir terminal, sem chamar engenheiro:

1. O AION está rodando?
2. Em qual modo?
3. Telemetria está ligada ou desligada?
4. Collective está ativo ou é só catálogo/lifecycle?
5. Quantas decisões tomou?
6. Quantos bypasses fez?
7. Quantos riscos bloqueou?
8. Por que decidiu bloquear/bypassar/continuar?
9. Quanto potencialmente economizou?
10. Onde está o audit?
11. Dá para exportar evidência?

### Auditoria do console atual

| # | Pergunta | Console responde hoje? | Onde responde | Gap |
|---|---|---|---|---|
| 1 | O AION está rodando? | ✅ Sim | Visão Geral — badge AION Online/Offline + sidebar CPU icon | Nenhum |
| 2 | Em qual modo? | ✅ Sim | Sidebar — pill `POC Decision-Only` / `POC Transparent` / etc. + Visão Geral hero | Nenhum |
| 3 | Telemetria ligada/desligada? | ✅ Sim | Sidebar — pill `Telemetria on/off` (laranja quando on, muted quando off) | Nenhum |
| 4 | Collective ativo ou só catálogo? | ⚠️ Parcial | Sidebar mostra `Collective on/off`. Página `/collective` mostra lifecycle completo. | Label precisa ser claro: "catálogo editorial — sem runtime enforcement" em modo POC |
| 5 | Quantas decisões tomou? | ✅ Sim | Operação — tabela completa; Visão Geral — métricas de decisões por módulo | Nenhum |
| 6 | Quantos bypasses fez? | ✅ Sim | Visão Geral — card "Chamadas evitadas"; Operação — filtro "Desviadas" | Nenhum |
| 7 | Quantos riscos bloqueou? | ✅ Sim | Visão Geral — card "Ameaças bloqueadas"; Operação — filtro "Bloqueadas" | Nenhum |
| 8 | Por que cada decisão? | ✅ Sim | Operação — modal de detalhe com caminho da decisão, módulo, razão, política aplicada | Nenhum |
| 9 | Quanto economizou? | ✅ Sim | Visão Geral — card "Economizado hoje"; Economia — gráfico "Com AION vs. Sem AION" | Usar `estimated_cost_saved` — não "economia real" sem baseline do cliente |
| 10 | Onde está o audit? | ✅ Sim | Sessões — histórico turn-by-turn com HMAC; Relatórios — aba Auditoria | Nenhum |
| 11 | Dá para exportar evidência? | ✅ Sim | Operação — botão "Exportar CSV"; Relatórios — dropdown PDF/CSV/JSON | Nenhum |

**Resultado:** 10 de 11 perguntas totalmente respondidas. 1 gap parcial (pergunta 4 — Collective precisa de label explícito em modo POC).

**Gap a corrigir:** Na página `/collective` e no indicador de sidebar, quando o modo for POC, exibir explicitamente: _"Catálogo de políticas — sem inteligência coletiva real e sem runtime enforcement neste modo."_

---

## 7. Cuidado com nomes comerciais e técnicos

| Evitar | Usar em vez |
|---|---|
| "NEMOS" como destaque de feature | "classificação local" / "memória operacional local" |
| "68% de bypass" sem benchmark validado | "taxa de bypass estimada" / dados reais do cliente |
| "economia real de R$ X" sem baseline do cliente | `estimated_cost_saved` / "economia estimada" |
| "políticas coletivas ativas" (se for só catálogo) | "catálogo editorial de políticas — sem runtime enforcement" |
| "redução de custo garantida" | "economia estimada com base no perfil de uso" |
| Shadow Mode como feature de POC | "fase 2 pós-POC — disponível após validação" |

---

## 8. Checklist POC Ready

Use antes de qualquer demo ou entrega de POC ao cliente.

```
[ ] docker-compose.poc-decision.yml sobe sem erro
[ ] /health responde 200
[ ] /ready responde 200
[ ] /v1/decide responde com Decision Contract válido
[ ] bypass funciona (saudação retorna decision: bypass)
[ ] prompt injection block funciona (attack retorna decision: block com razão)
[ ] PII detection funciona OU está claramente fora do escopo documentado
[ ] console mostra modo atual (Decision-Only visível)
[ ] console mostra status de telemetria (OFF em modo POC)
[ ] console mostra decisões em tempo real
[ ] console mostra audit trail legível
[ ] console mostra resumo de economia/risco estimado
[ ] export CSV/JSON funciona a partir do console
[ ] documentação diz que nada sai do ambiente do cliente
[ ] documentação diz que Redis é local/do cliente
[ ] documentação separa POC vs Shadow vs Full
[ ] quickstart testado em máquina limpa (sem histórico Baluarte)
```

---

## 9. Linha do tempo de adoção

```
POC (agora)
  Decision-Only
  Foco: decisão, economia, risco, auditabilidade
  Sem chave LLM, sem telemetria, sem Collective

        ↓  validação e aprovação interna

Shadow Mode (fase 2)
  Observação real com telemetria opt-in
  Políticas em teste paralelo sem afetar produção
  Primeiros dados reais de divergência

        ↓  confiança estabelecida

Full Version (fase 3)
  NOMOS ML adaptativo
  METIS — compressão de contexto
  Collective — inteligência entre tenants (opt-in com DPA)
  AION Cloud Plane (opcional)
  SSO/RBAC corporativo
```
