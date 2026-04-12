# AION Console — UX Copy Guide

## Voice & Tone

### Who We Are
A helpful control panel that empowers technical and non-technical users to manage AI behavior confidently.

### Voice Attributes
| Attribute | We are | We are NOT |
|-----------|--------|------------|
| **Clear** | "Bypass rate: 42% of questions answered without AI" | "Approximately 42% of incoming queries were successfully intercepted by the bypass mechanism" |
| **Friendly** | "No data yet. Send a message to get started." | "Error: No data available in the current dataset." |
| **Empowering** | "Choose how your AI behaves" | "AI behavior is determined by the following parameters" |
| **Honest** | "Disabling this may increase costs" | "Consider the implications" |

### Tone by Context

| Context | Tone | Example (PT-BR) |
|---------|------|-----------------|
| **Success** | Confident, brief | "Comportamento atualizado com sucesso." |
| **Error** | Empathetic, actionable | "Não foi possível conectar ao AION. Verifique se o serviço está rodando." |
| **Warning** | Clear, no alarm | "Desativar o desvio fará todas as mensagens serem enviadas para a IA, aumentando o custo." |
| **Empty state** | Encouraging, directional | "Ainda sem dados. Envie uma mensagem para começar." |
| **Onboarding** | Warm, progressive | "Configure como sua IA se comporta — sem precisar de código." |
| **Approval flow** | Neutral, status-focused | "Aguardando aprovação do Gerente de Produto." |

---

## Writing Rules

### 1. Labels (max 30 chars)
- Use nouns or noun phrases: "Taxa de desvio", "Bypass rate"
- No periods at the end
- Capitalize first word only (sentence case)

### 2. Descriptions & Helper Text (max 200 chars)
- One sentence explaining what the control does
- Start with "How...", "What...", or a verb phrase
- End with period

### 3. Tooltips (max 120 chars)
- Explain the "why" or "how", not just restate the label
- One sentence, no jargon without explanation
- Use parenthetical clarifications: "Latência (tempo de resposta)"

### 4. CTAs (max 25 chars)
- Start with a verb: "Salvar", "Aplicar", "Exportar"
- Be specific: "Salvar comportamento" not "Salvar"
- Match the action to the label

### 5. Error Messages
Structure: **What happened** + **Why** + **How to fix**
```
"Não foi possível salvar. O serviço AION não está respondendo. Verifique se está rodando e tente novamente."
```

### 6. Empty States
Structure: **What this is** + **Why it's empty** + **How to start**
```
"Nenhuma operação registrada. Quando o AION processar requisições, as decisões aparecerão aqui."
```

### 7. Confirmation Dialogs
- Title: action as question — "Aplicar novo comportamento?"
- Body: consequence — "A IA começará a se comportar de acordo com essas configurações imediatamente."
- Buttons: action verbs — "Aplicar agora" / "Cancelar"

### 8. Toast Notifications
- Success: past tense — "Configuração salva com sucesso."
- Error: could not + action — "Não foi possível salvar. Tente novamente."
- Max one sentence.

---

## Bilingual Glossary

Consistent terminology across both languages. Use these terms everywhere.

| Concept | PT-BR | EN | Notes |
|---------|-------|----|-------|
| Bypass | Desvio | Bypass | "Desvio inteligente" for the feature name |
| Bypass rate | Taxa de desvio | Bypass rate | |
| Routing | Roteamento | Routing | |
| Fallback | Fallback | Fallback | Keep English in both languages |
| Fallback chain | Cadeia de fallback | Fallback chain | |
| Latency | Latência | Latency | Always explain: "tempo de resposta" |
| Token | Token | Token | Keep English in both languages |
| Model | Modelo | Model | |
| Provider | Provedor | Provider | |
| Prompt | Prompt | Prompt | Keep English in both languages |
| Threshold | Limite | Threshold | "Limite de decisão" for UI |
| Confidence | Confiança | Confidence | |
| Safe mode | Modo seguro | Safe mode | |
| Behavior dial | Dial de comportamento | Behavior dial | |
| Hot reload | Recarga instantânea | Hot reload | |
| Tenant | Tenant | Tenant | Keep English in both languages |
| Intent | Intenção | Intent | Used in ESTIXE context |
| Policy | Política | Policy | |
| Guardrail | Proteção | Guardrail | Prefer "proteção" in PT-BR |
| Draft | Rascunho | Draft | Approval workflow |
| Under review | Em revisão | Under review | Approval workflow |
| Live | Em produção | Live | Approval workflow |

---

## Approval Workflow Copy

### Flow
```
Analista/Dev cria → PM aprova → Tech Manager aprova → Produção
```

### States & Messaging

| State | Badge (PT) | Badge (EN) | Message (PT) | Message (EN) |
|-------|------------|------------|--------------|--------------|
| Created | Rascunho | Draft | — | — |
| Submitted | Em revisão | Under review | Alteração enviada para aprovação. | Change submitted for approval. |
| PM approved | Aprovado (Produto) | Approved (Product) | Aguardando aprovação do Gerente de Tecnologia. | Awaiting Tech Manager approval. |
| Tech approved | Aprovado (Tech) | Approved (Tech) | Aguardando aprovação do Gerente de Produto. | Awaiting Product Manager approval. |
| Both approved | Pronto para produção | Ready for production | Ambos aprovaram. Pronto para produção. | Both approved. Ready for production. |
| Deployed | Em produção | Live | Alteração aplicada em produção. | Change deployed to production. |
| Rejected | Rejeitado | Rejected | Alteração rejeitada. Verifique os comentários. | Change rejected. Check comments. |

---

## i18n Implementation Notes

### JSON Key Structure
```
section.element_type_name
```
Examples:
- `status.metric_latency` — label
- `status.metric_latency_tooltip` — help text
- `policies.dial_objectivity_low` — slider endpoint

### Interpolation
Use `{{variable}}` for dynamic values:
```json
"latency_value": "{{value}}ms"
```

### Pluralization
For future implementation, use ICU format:
```json
"requests_count": "{count, plural, =0 {Nenhuma requisição} one {# requisição} other {# requisições}}"
```

### Framework Compatibility
These JSON files are compatible with:
- **next-intl** (Next.js)
- **i18next** / **react-i18next** (React)
- **vue-i18n** (Vue)
- **@angular/localize** (Angular)

### Adding a New Language
1. Copy `en.json` to `{locale}.json`
2. Translate all values (keys stay the same)
3. Verify all keys match using the validation script
4. Add locale to the app's language selector

---

## Validation Checklist

- [ ] All keys in `pt-BR.json` exist in `en.json` and vice-versa
- [ ] Labels are under 30 characters
- [ ] Tooltips are under 120 characters
- [ ] Descriptions are under 200 characters
- [ ] CTAs start with a verb
- [ ] Error messages follow "What + Why + Fix" structure
- [ ] Empty states follow "What + Why + Start" structure
- [ ] No raw technical jargon without explanation
- [ ] Approval workflow states are consistent
- [ ] Glossary terms are used consistently throughout
