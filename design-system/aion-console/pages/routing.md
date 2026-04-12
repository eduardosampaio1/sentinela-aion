# Page Override: Routing (Roteamento)

> Overrides MASTER.md for the Routing page only.

## Purpose
Answer: "Which brain for each problem?" — map prompt types to AI models.

## Layout Override

```
┌──────────────────────────────────────────────┐
│ Priority Slider                              │
│ Cost ○───────────●───────────○ Quality       │
├──────────────────────────────────────────────┤
│ Available Models (horizontal cards)          │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│ │ gpt-4o   │ │gpt-4o-   │ │ claude   │     │
│ │ mini     │ │          │ │ sonnet   │     │
│ │ $0.15/1M │ │ $2.50/1M │ │ $3.00/1M │     │
│ │ [Active] │ │ [Active] │ │[Fallback]│     │
│ └──────────┘ └──────────┘ └──────────┘     │
├──────────────────────────────────────────────┤
│ Routing Rules (table)                        │
│ Type      │ Model        │ Condition         │
│ Simple    │ gpt-4o-mini  │ < 50 tokens       │
│ Complex   │ gpt-4o       │ > 200 tokens      │
│ Code      │ claude-sonnet│ contains code      │
│ Default   │ gpt-4o-mini  │ —                  │
│                              [+ Add Rule]    │
├──────────────────────────────────────────────┤
│ Fallback Chain                               │
│ 1. gpt-4o-mini  2. gpt-4o  3. gemini-flash  │
│ [drag to reorder]           [+ Add Fallback] │
├──────────────────────────────────────────────┤
│ Max Latency: [●─────── 3000ms]              │
└──────────────────────────────────────────────┘
```

## Component-Specific Rules

### Priority Slider
- Full width at top of page
- Single slider: Cost ← → Quality
- Left end: "Cost" with dollar icon
- Right end: "Quality" with sparkle icon
- Tooltip explains how this affects model selection

### Model Cards
- Horizontal scrollable row (4+ models)
- Each card shows: name, provider logo (SVG), cost/1M tokens, latency, status badge
- Status: Active (green), Inactive (gray), Fallback Only (yellow)
- Click to expand: full capabilities, max tokens, detailed pricing
- Cards are read-only here — editing happens in config files

### Routing Rules Table
- Editable inline table
- Columns: Prompt Type (dropdown), Model (dropdown), Condition (text/dropdown)
- Prompt types: Simple, Complex, Creative, Code, Analysis, Default
- "Add Rule" button at bottom
- "Remove" action per row (trash icon, with confirmation)
- Default row cannot be removed (last resort)

### Fallback Chain
- Drag-and-drop reorderable list
- Each item: model name + provider + remove button
- Visual: numbered circles connected by dotted line
- Warning banner if empty: "No fallback configured. If the primary model fails, requests will error."
- "Add Fallback" opens a model selector dropdown

### Max Latency Slider
- Range: 500ms - 30000ms
- Default: 3000ms
- Shows current value in Fira Code
- Tooltip: "If the model doesn't respond in time, AION tries the next fallback"

## Data Source
- `GET /v1/models` — model registry
- `config/models.yaml` — model definitions (via hot-reload API)
- Routing rules: future API (currently YAML-only)
