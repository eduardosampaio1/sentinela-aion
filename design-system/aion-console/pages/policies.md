# Page Override: Policies (Comportamento da IA)

> Overrides MASTER.md for the Policies/Behavior page only.

## Purpose
Answer: "How do I want my AI to behave?" — adjust behavior without code.

## Layout Override

```
┌──────────────────────────────────────────────┐
│ Quick Presets (horizontal cards)             │
│ [Direct & Economic] [Explain More] [Balanced]│
├──────────────────────────────────────────────┤
│ Behavior Dials                               │
│                                              │
│ Objectivity    ●─────────────○  Direct       │
│ Verbosity      ○──────●──────○  Balanced     │
│ Economy        ○─────────────●  Min Cost     │
│ Explanation    ●─────────────○  Answer Only   │
│ Confidence     ○──────●──────○  Medium       │
│ Safe Mode      ○──────●──────○  Balanced     │
│ Formality      ○──────●──────○  Balanced     │
│                                              │
├──────────────────────────────────────────────┤
│ [Approval Badge]  [Reset Default] [Save]     │
└──────────────────────────────────────────────┘
```

## Component-Specific Rules

### Quick Presets
- Horizontal row of 3-4 cards at the top
- Active preset: filled background (`bg-primary text-white`)
- Inactive: ghost style (`border-primary text-primary`)
- Clicking a preset sets all dials to pre-defined values
- "Custom" appears when any dial is manually changed from preset

### Behavior Dials (Sliders)
- Each dial is a full-width row:
  - Left label (low end): text-muted, 12px
  - Slider track: centered, h-2
  - Right label (high end): text-muted, 12px
  - Dial name: bold, above the slider
  - Description: muted, below the name
  - Tooltip icon: `HelpCircle`, right of name
- Slider values: 0-100, snapping to 10s for simplicity
- Visual feedback: the active range fills with primary color
- Real-time preview: changing a dial shows predicted impact (optional tooltip)

### Approval Integration
- When user is analyst/dev: "Save" creates a Draft
- Badge shows current approval state
- "Submit for approval" button appears after saving
- PM and Tech Manager see "Approve" / "Reject" buttons
- History: expandable section showing who changed what and when

### Save Flow
1. User adjusts dials → changes are unsaved (yellow indicator)
2. "Save" → confirmation dialog: "Apply new behavior?"
3. If analyst/dev → creates Draft, shows "Submit for approval"
4. If manager → applies directly (or sends to other manager)
5. Toast: "Behavior updated" or "Submitted for approval"

### Reset
- "Reset to default" is secondary/ghost button
- Confirmation dialog: "Restore all dials to default? Custom settings will be lost."
- Does NOT reset approval chain — creates new change

## Data Source
- `GET /v1/behavior` — current dial values
- `PUT /v1/behavior` — update dials
- `DELETE /v1/behavior` — reset to defaults
