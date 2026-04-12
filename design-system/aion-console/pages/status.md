# Page Override: Status (Visao Geral)

> Overrides MASTER.md for the Status page only.

## Purpose
Answer: "Is everything under control?" — give confidence in 3 seconds.

## Layout Override

```
┌──────────────────────────────────────────────┐
│ [●] Status Badge (Online/Offline/Degraded)   │
├──────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│ │ Latency │ │ Bypass  │ │ AI      │        │
│ │ 142ms   │ │ Rate    │ │ Calls   │        │
│ │         │ │ 38%     │ │ 1,247   │        │
│ └─────────┘ └─────────┘ └─────────┘        │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│ │ Savings │ │ Top     │ │ Error   │        │
│ │ R$47.20 │ │ Model   │ │ Rate    │        │
│ │         │ │ gpt-4o  │ │ 0.3%    │        │
│ └─────────┘ └─────────┘ └─────────┘        │
├──────────────────────────────────────────────┤
│ Recent Fallbacks (collapsible list)          │
└──────────────────────────────────────────────┘
```

## Component-Specific Rules

### Status Badge (Hero)
- Position: top of page, full width
- Online: green pulsing dot + "Online" text + "AION is running normally"
- Offline: red static dot + error message
- Degraded: yellow static dot + limitation description
- Size: large — this is the first thing users see

### Metric Cards
- Grid: 3 columns (desktop), 2 columns (tablet), 1 column (mobile)
- Each card: icon (Lucide) + value (Fira Code, 2rem, bold) + label (uppercase, small)
- Hover: subtle shadow increase (no movement)
- Tooltip icon: `HelpCircle` from Lucide, appears on hover of "?" icon

### Values Format
- Latency: `142ms` (Fira Code, teal-700)
- Percentages: `38%` with color coding (green < 5% error, yellow 5-15%, red > 15%)
- Currency: `R$ 47.20` (with locale-appropriate formatting)
- Counts: `1,247` (with thousand separators)

### Auto-Refresh
- Toggle in top-right corner
- When active: subtle rotating icon + "Updating every 30s" tooltip
- Default: ON

### Fallbacks Section
- Collapsible by default (collapsed)
- Table: From model → To model → Reason → Timestamp
- Empty state: green checkmark + "No recent fallbacks"

## Data Source
- `GET /v1/stats` — all metrics
- `GET /v1/events?type=fallback` — fallback list
- `GET /health` — online/offline status
