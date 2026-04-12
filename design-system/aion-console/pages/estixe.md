# Page Override: ESTIXE (Protecao)

> Overrides MASTER.md for the ESTIXE/Protection page only.

## Purpose
Answer: "What can my AI NOT do?" — set boundaries and save cost.

## Layout Override

```
┌──────────────────────────────────────────────┐
│ Smart Bypass                         [ON/OFF]│
│ "Answers simple questions without AI"        │
├──────────────────────────────────────────────┤
│ Bypass Categories                            │
│ ┌────────────┐ ┌────────────┐              │
│ │ Greeting ✓ │ │ Farewell ✓ │              │
│ │ "oi, olá"  │ │ "tchau"    │              │
│ └────────────┘ └────────────┘              │
│ ┌────────────┐ ┌────────────┐              │
│ │ Gratitude ✓│ │ Confirm  ✓ │              │
│ │ "obrigado" │ │ "ok, sim"  │              │
│ └────────────┘ └────────────┘              │
│                         [+ Add Category]     │
├──────────────────────────────────────────────┤
│ Content Blocks                               │
│ Category        │ Action    │ [Remove]       │
│ Adult content   │ Reject    │   ×            │
│ Violence        │ Warn      │   ×            │
│                         [+ Add Block]        │
├──────────────────────────────────────────────┤
│ Security Rules                               │
│ ✓ Prompt injection protection                │
│ ✓ System prompt protection                   │
│ ✓ Sensitive data detection                   │
│ ✓ Token limit (max: 4096)                   │
├──────────────────────────────────────────────┤
│ Decision Thresholds                          │
│ Bypass confidence  ●──────────○  0.85        │
│ Block confidence   ○──────●───○  0.70        │
└──────────────────────────────────────────────┘
```

## Component-Specific Rules

### Smart Bypass Toggle (Hero)
- Top of page, prominent
- Large toggle switch (56px wide)
- Description text below
- When toggling OFF: warning dialog — "All messages will go to AI, increasing cost"
- When ON: shows bypass stats (how many saved today)

### Bypass Category Cards
- Grid of cards (2 columns desktop, 1 mobile)
- Each card: category name, toggle, example phrases, edit button
- Toggle: enables/disables that category
- "Edit examples" expands to show all training phrases
- "Add category" opens a form: name + initial examples + auto-response
- Cards use slightly tinted backgrounds per category for visual distinction

### Content Blocks
- Simple editable table
- Columns: Category (text input), Action (dropdown: Reject/Warn/Redirect)
- "Add block" at bottom
- "Remove" with confirmation dialog
- Action badges: Reject (red), Warn (yellow), Redirect (blue)

### Security Rules
- List of toggleable rules with descriptions
- Each rule: toggle + name + description + severity indicator
- Critical rules (prompt injection, system leak): show warning when disabling
- Non-critical (PII detection): simple toggle
- Token limit: shows editable number input when expanded

### Decision Thresholds
- Two sliders:
  - Bypass confidence: 0.0 - 1.0 (default 0.85)
  - Block confidence: 0.0 - 1.0 (default 0.70)
- Show current value in Fira Code next to slider
- Tooltips explain what happens at different thresholds
- Warning when lowering below recommended values

### Warning System
- Orange banner for risky changes (lowering thresholds, disabling security)
- Red banner for critical changes (disabling all bypass, removing all security)
- Banners appear inline, near the changed control
- Icon: `AlertTriangle` from Lucide

## Data Source
- `POST /v1/estixe/intents/reload` — reload intents from YAML
- `POST /v1/estixe/policies/reload` — reload policies from YAML
- `aion/estixe/data/intents.yaml` — intent definitions
- `config/policies.yaml` — policy rules
