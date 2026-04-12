# Design System Master File — AION Console

> **LOGIC:** When building a specific page, first check `design-system/aion-console/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** AION Console
**Type:** Operational AI Control Panel (NOT a landing page or analytics dashboard)
**Generated:** 2026-04-10
**Stack:** Next.js 14+ / React / TypeScript / Tailwind CSS
**Icon Set:** Lucide React (consistent, MIT licensed)
**Chart Library:** Recharts (React-native, composable)

---

## Identity

The AION Console is a **control panel**, not a dashboard. Users come here to **change** things, not just observe. Every screen should answer a question:

| Section | Question |
|---------|----------|
| Status | "Is everything under control?" |
| Policies | "How do I want my AI to behave?" |
| Routing | "Which brain for each problem?" |
| ESTIXE | "What can my AI NOT do?" |
| Operations | "Why did AION make that decision?" |

---

## Color Palette

### Light Mode (Primary)

| Role | Hex | Tailwind | CSS Variable |
|------|-----|----------|--------------|
| Primary | `#0F766E` | `teal-700` | `--color-primary` |
| Secondary | `#14B8A6` | `teal-500` | `--color-secondary` |
| Accent/CTA | `#0369A1` | `sky-700` | `--color-cta` |
| Background | `#F0FDFA` | `teal-50` | `--color-bg` |
| Surface | `#FFFFFF` | `white` | `--color-surface` |
| Text Primary | `#134E4A` | `teal-900` | `--color-text` |
| Text Muted | `#475569` | `slate-600` | `--color-text-muted` |
| Border | `#E2E8F0` | `slate-200` | `--color-border` |
| Success | `#15803D` | `green-700` | `--color-success` |
| Warning | `#A16207` | `yellow-700` | `--color-warning` |
| Error | `#B91C1C` | `red-700` | `--color-error` |

### Dark Mode

| Role | Hex | Tailwind | CSS Variable |
|------|-----|----------|--------------|
| Primary | `#14B8A6` | `teal-500` | `--color-primary` |
| Secondary | `#2DD4BF` | `teal-400` | `--color-secondary` |
| Accent/CTA | `#38BDF8` | `sky-400` | `--color-cta` |
| Background | `#0C0A09` | `stone-950` | `--color-bg` |
| Surface | `#1C1917` | `stone-900` | `--color-surface` |
| Text Primary | `#F0FDFA` | `teal-50` | `--color-text` |
| Text Muted | `#94A3B8` | `slate-400` | `--color-text-muted` |
| Border | `#334155` | `slate-700` | `--color-border` |
| Success | `#4ADE80` | `green-400` | `--color-success` |
| Warning | `#FACC15` | `yellow-400` | `--color-warning` |
| Error | `#F87171` | `red-400` | `--color-error` |

**Design Notes:** Trust teal + professional blue. Teal conveys reliability and technology. Sky blue for CTAs creates clear action hierarchy.

---

## Typography

- **Headings:** Fira Code (monospace feel = technical credibility)
- **Body:** Fira Sans (clean, highly readable)
- **Code/Data:** Fira Code (natural fit for metrics and values)

```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

### Type Scale

| Element | Font | Size | Weight | Line Height |
|---------|------|------|--------|-------------|
| Page title | Fira Code | 24px / 1.5rem | 700 | 1.2 |
| Section title | Fira Code | 20px / 1.25rem | 600 | 1.3 |
| Card title | Fira Sans | 16px / 1rem | 600 | 1.4 |
| Body | Fira Sans | 14px / 0.875rem | 400 | 1.5 |
| Small/Caption | Fira Sans | 12px / 0.75rem | 400 | 1.5 |
| Metric value | Fira Code | 32px / 2rem | 700 | 1.1 |
| Badge | Fira Sans | 12px / 0.75rem | 500 | 1 |

---

## Layout

### Structure
```
┌─────────────────────────────────────────────┐
│ Top Bar (logo, tenant selector, user menu)  │
├────────┬────────────────────────────────────┤
│        │                                    │
│ Side   │  Main Content Area                 │
│ Nav    │  (max-w-7xl, centered)             │
│        │                                    │
│ 240px  │  Responsive: collapses to icons    │
│        │  at < 1024px, drawer at < 768px    │
│        │                                    │
├────────┴────────────────────────────────────┤
│ (No footer — operational panels don't need) │
└─────────────────────────────────────────────┘
```

### Breakpoints

| Breakpoint | Width | Sidebar | Grid |
|------------|-------|---------|------|
| Mobile | < 768px | Hidden (hamburger) | 1 col |
| Tablet | 768-1023px | Icons only (64px) | 2 col |
| Desktop | 1024-1439px | Full (240px) | 3 col |
| Wide | 1440px+ | Full (240px) | 4 col |

### Spacing

| Token | Value | Tailwind | Usage |
|-------|-------|----------|-------|
| xs | 4px | `p-1` | Tight gaps, badge padding |
| sm | 8px | `p-2` | Icon gaps, inline spacing |
| md | 16px | `p-4` | Standard card padding |
| lg | 24px | `p-6` | Section padding |
| xl | 32px | `p-8` | Page margins |
| 2xl | 48px | `p-12` | Section margins |

### Z-Index Scale

| Level | Value | Usage |
|-------|-------|-------|
| Base | 0 | Normal content |
| Dropdown | 10 | Menus, selects |
| Sticky | 20 | Sidebar, top bar |
| Modal overlay | 30 | Backdrop |
| Modal | 40 | Dialog content |
| Toast | 50 | Notifications |

---

## Component Specs

### Status Badges

```
Online    → bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400
Offline   → bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400
Degraded  → bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400
```

With pulsing dot indicator: `animate-pulse` for Online, static for others.

### Approval Badges

```
Draft         → bg-slate-100 text-slate-600
Under review  → bg-amber-100 text-amber-700
Approved (PM) → bg-blue-100 text-blue-700
Approved (Tech) → bg-cyan-100 text-cyan-700
Ready for prod → bg-green-100 text-green-700
Live          → bg-green-500 text-white (solid)
Rejected      → bg-red-100 text-red-700
```

### Metric Cards

```css
.metric-card {
  /* Light */
  background: white;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 24px;
  
  /* Structure */
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-value {
  font-family: 'Fira Code';
  font-size: 2rem;
  font-weight: 700;
  color: var(--color-primary);
}

.metric-label {
  font-family: 'Fira Sans';
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
```

### Buttons

| Type | Usage | Style |
|------|-------|-------|
| Primary | Main CTAs (Save, Apply, Deploy) | bg-cta text-white |
| Secondary | Alternative actions (Cancel, Reset) | border-primary text-primary bg-transparent |
| Danger | Destructive actions (Remove, Reject) | bg-red-600 text-white |
| Ghost | Inline actions (Edit, Filter) | text-primary hover:bg-primary/10 |

### Sliders / Dials

For the Behavior Dial section (Policies):
- Track: `bg-slate-200 dark:bg-slate-700` (h-2, rounded-full)
- Thumb: `bg-primary` (w-5 h-5, rounded-full, shadow-md)
- Active range: `bg-primary` (fills from left)
- Labels at endpoints: text-xs, text-muted
- Current value: displayed above thumb or in adjacent card

### Toggle Switches

For ESTIXE on/off controls:
- Off: `bg-slate-300 dark:bg-slate-600`
- On: `bg-primary`
- Size: 44px wide x 24px tall (meets touch target)
- Transition: 200ms ease

### Cards

```css
.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 24px;
  transition: box-shadow 200ms ease;
}

.card:hover {
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}

/* Clickable cards get cursor-pointer */
.card[role="button"] {
  cursor: pointer;
}
```

### Tables (Operations)

- Header: `bg-slate-50 dark:bg-slate-800` sticky
- Rows: alternating `bg-white` / `bg-slate-50` (subtle)
- Hover: `bg-primary/5`
- Cell padding: `px-4 py-3`
- Font: Fira Sans 14px, Fira Code for values/timestamps
- Clickable rows: `cursor-pointer`

### Toasts

- Position: top-right, stacked
- Success: left border `green-500`
- Error: left border `red-500`
- Warning: left border `yellow-500`
- Auto-dismiss: 5s for success, persistent for errors
- Animation: slide-in from right, 200ms

### Modals / Confirmation Dialogs

- Overlay: `bg-black/50 backdrop-blur-sm`
- Card: `bg-white dark:bg-stone-900`, `rounded-2xl`, `p-8`
- Max width: 480px
- Actions: right-aligned, primary button on right
- Close: X button top-right + Escape key

---

## Charts

| Data Type | Chart Type | Library |
|-----------|-----------|---------|
| Trends (latency, costs over time) | Line Chart | Recharts |
| Real-time streaming (events) | Streaming Area Chart | Recharts |
| Distribution (model usage) | Donut Chart | Recharts |
| Comparison (cost vs quality) | Bar Chart | Recharts |

### Chart Colors
- Primary series: `#0F766E` (teal-700)
- Secondary series: `#0369A1` (sky-700)
- Tertiary series: `#7C3AED` (violet-600)
- Grid: `#E2E8F0` (slate-200)
- Fill opacity: 20%

---

## Animation

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro-interaction | 150ms | ease | Button hover, toggle |
| Transition | 200ms | ease | Card hover, state change |
| Entrance | 300ms | ease-out | Modal open, toast appear |
| Data update | 500ms | ease-in-out | Chart transitions, metric counters |

**Always respect `prefers-reduced-motion`**: disable all non-essential animations.

---

## Accessibility

- Color contrast: 4.5:1 minimum (WCAG AA)
- Touch targets: 44x44px minimum
- Focus ring: `ring-2 ring-primary ring-offset-2`
- All icon buttons: `aria-label` required
- Form inputs: visible `<label>` required (no placeholder-only)
- Tab order: matches visual order
- Skeleton loaders for async content (no blank screens)

---

## Anti-Patterns (Do NOT Use)

- Emojis as icons — use Lucide React SVGs
- Missing `cursor-pointer` on clickable elements
- Layout-shifting hover effects (no `scale` transforms on cards)
- Low contrast text (< 4.5:1 ratio)
- Instant state changes without transitions
- Invisible focus states
- Placeholder-only form labels
- Continuous decorative animations
- Horizontal scroll on mobile
- Content behind fixed navbar

---

## Pre-Delivery Checklist

- [ ] No emojis used as icons (Lucide React SVGs only)
- [ ] All icons from consistent set (Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Both light and dark mode tested
- [ ] Text contrast 4.5:1 minimum in both modes
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive at 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed elements
- [ ] No horizontal scroll on mobile
- [ ] Skeleton loaders for all async content
- [ ] All form inputs have visible labels
- [ ] All icon buttons have aria-labels
- [ ] Toast notifications accessible (role="alert")
- [ ] i18n keys used (no hardcoded strings)
