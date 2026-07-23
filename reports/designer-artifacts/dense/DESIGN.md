# Nimbus — Design System

## 1. Visual Theme
Calm, dense, developer-grade. Dark-first. Content over chrome. Nothing decorative earns its pixels.

## 2. Color Palette & Roles
Semantic tokens only — never raw hex in a surface.
- `color.bg.canvas` = #0B0E14   (app background)
- `color.bg.surface` = #141922  (cards, panels)
- `color.bg.raised` = #1C2230   (menus, popovers)
- `color.border.subtle` = #232A38
- `color.text.primary` = #E6EAF2  (contrast 12.6:1 on canvas)
- `color.text.secondary` = #9BA6B8 (contrast 5.1:1 on canvas)
- `color.accent.default` = #4C8DFF (primary action)
- `color.accent.hover` = #6BA0FF
- `color.danger.default` = #FF5C5C
- `color.success.default` = #3FCF8E

## 3. Typography Rules
- Family: `Inter` (UI), `JetBrains Mono` (code/values).
- Scale (rem): `text.xs` 0.75 / `text.sm` 0.875 / `text.md` 1.0 / `text.lg` 1.25 / `text.xl` 1.5.
- Weights: 400 body, 500 labels, 600 headings. Line-height 1.5 body, 1.25 headings.

## 4. Component Stylings
- `Button`: variants `primary` (accent bg), `secondary` (surface bg + subtle border), `ghost`, `danger`.
  Radius `radius.md` 8px. Height 36px. Focus ring 2px `color.accent.default` at 2px offset.
- `Input`: surface bg, subtle border, 36px height, `text.sm` label above.
- `Table`: 44px rows, sticky header `bg.raised`, zebra off, row hover `bg.raised`.
- `Badge`: pill, `text.xs`, semantic color roles.

## 5. Layout Principles
- Spacing scale (px, 4-based): `space.1` 4 / `space.2` 8 / `space.3` 12 / `space.4` 16 / `space.6` 24 / `space.8` 32.
- 12-column grid, max content width 1200px, gutter `space.6`.
- Left nav 240px, collapses to icons < 960px.

## 6. Depth & Elevation
Two levels only: surface (flat) and raised (`shadow.sm` = 0 1px 2px rgba(0,0,0,.4)). No heavy shadows.

## 7. Do's and Don'ts
- DO use semantic tokens; DO keep one primary action per view.
- DON'T hardcode hex or px outside the scale; DON'T use color as the only state signal.

## 8. Responsive Behavior
Breakpoints: `sm` 640 / `md` 960 / `lg` 1200. Below `md`: nav collapses, tables become stacked cards.

## 9. Agent Prompt Guide
When generating UI: dark surfaces, semantic tokens, Inter, 4px spacing rhythm, one primary action,
visible focus rings, every interactive state defined, WCAG AA contrast minimum.
