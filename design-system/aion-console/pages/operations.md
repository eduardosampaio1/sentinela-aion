# Page Override: Operations (Operacao)

> Overrides MASTER.md for the Operations page only.

## Purpose
Answer: "Why did AION make that decision?" — real-time transparency.

## Layout Override

```
┌──────────────────────────────────────────────┐
│ Filters Bar                                  │
│ [All] [Bypassed] [Routed] [Blocked] [Errors] │
│ Model: [▼ All]  Tenant: [▼ All]  Date: [──] │
├──────────────────────────────────────────────┤
│ Events Table                                 │
│ When    │ Input      │ Decision │ Model │ ms │
│ 19:14   │ "Oi, tudo" │ Bypass   │ —     │ 2  │
│ 19:14   │ "Analyze.."│ Routed   │ gpt4o │ 847│
│ 19:13   │ "Ignore.." │ Blocked  │ —     │ 12 │
│ 19:12   │ "What is.."│ Fallback │ mini  │ 3200│
│ ...     │            │          │       │    │
├──────────────────────────────────────────────┤
│ Auto-refresh [ON ●]    [Export ▼] [Refresh]  │
└──────────────────────────────────────────────┘
```

## Component-Specific Rules

### Filter Bar
- Sticky at top of content area (below page header)
- Decision type filters: pill buttons (toggle style)
  - All (default, no filter)
  - Bypassed: teal badge
  - Routed: blue badge
  - Blocked: red badge
  - Errors: orange badge
- Additional filters: dropdown selectors for Model, Tenant, Date range
- "Clear filters" link appears when any filter is active

### Events Table
- Primary component of this page — takes most of the viewport
- Columns: Timestamp, Input (truncated), Decision, Policy, Model, Response Time, Cost
- Sortable by clicking column headers
- Clickable rows → opens detail modal
- Decision column uses colored badges:
  - Bypassed: `bg-teal-100 text-teal-700`
  - Routed: `bg-blue-100 text-blue-700`
  - Blocked: `bg-red-100 text-red-700`
  - Fallback: `bg-amber-100 text-amber-700`
  - Error: `bg-red-500 text-white`
- Response time: color coded (green < 500ms, yellow 500-2000ms, red > 2000ms)
- Input text: truncated to ~50 chars, full text on hover/click
- Font: Fira Sans for text, Fira Code for timestamps/values

### Event Detail Modal
- Opens on row click
- Full width up to 640px
- Sections:
  1. **Input**: full user message
  2. **Decision Path**: visual flow (e.g., "ESTIXE → Bypass (greeting, confidence: 0.92)")
  3. **Policies Applied**: list of policies that were evaluated
  4. **Response**: full AI response (if routed) or bypass response
  5. **Metadata**: model, tokens, cost, tenant, timestamp
  6. **Error**: (only if error) stack trace or error message

### Decision Path Visualization
- Simple horizontal flow:
  ```
  Input → [ESTIXE] → [NOMOS] → [METIS] → Output
           ↓ bypass    ↓ route   ↓ optimize
  ```
- Highlight the active path for this specific event
- Gray out skipped steps

### Auto-Refresh
- Toggle in bottom bar
- When ON: new events appear at top with subtle highlight animation (200ms)
- Interval: 5 seconds
- Visual indicator: pulsing dot next to "Auto-refresh"
- When OFF: manual "Refresh" button

### Export
- Dropdown: CSV or JSON
- Exports currently filtered data
- Filename: `aion-events-{date}-{filter}.csv`

### Empty State
- Large centered illustration (or Lucide icon `Activity`)
- "No operations recorded"
- "When AION processes requests, decisions will appear here in real time."
- CTA: "Send a test request" (links to API docs or curl example)

### Connection Error State
- Full-width warning banner
- `AlertTriangle` icon
- "Connection lost. Operations are not being updated."
- CTA: "Try reconnecting" (attempts to re-establish connection)

## Performance Notes
- Virtualized table for large datasets (use `@tanstack/react-virtual`)
- Pagination: 50 events per page, infinite scroll or explicit pagination
- Skeleton loader: 5 rows of animated placeholders while loading

## Data Source
- `GET /v1/events` — recent events list
- `GET /v1/stats` — aggregate stats for filter counts
