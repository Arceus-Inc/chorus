---
name: wcag-conformance
description: The accessibility floor every UI spec must clear — WCAG 2.1 AA in practice — expressed as concrete, checkable requirements rather than a standard to go read. Treat it as a gate, not a nice-to-have.
when_to_use: Read on every UI beat before the design_critic runs, and it is the backbone of the monthly accessibility audit routine. The specialist skills (color-contrast, keyboard-and-focus) drill into the two hardest areas.
---

# WCAG Conformance (AA floor)

Accessibility is not a polish pass — it is a floor the design must clear before it ships. A model
fluent in visuals will routinely produce inaccessible defaults (low-contrast gray text, icon-only
buttons, color-only status, keyboard traps) because they *look* clean. This skill turns "be
accessible" into a checklist you can actually verify. When `DESIGN.md` names a stricter bar, follow it.

## The one rule

**Every meaning conveyed visually must also be conveyed non-visually.** Color, position, size, and
motion are *additions* to an accessible base — never the sole carrier of information, action, or state.

## The AA floor, as checkable requirements

- **Contrast**: body/UI text ≥ 4.5:1, large text (≥24px or ≥19px bold) and meaningful non-text (icons,
  control borders, focus rings) ≥ 3:1. See `color-contrast`.
- **Color is never alone**: error isn't only red, "selected" isn't only a highlight — pair it with an
  icon, label, underline, or shape. (WCAG 1.4.1)
- **Keyboard**: every interactive element is reachable and operable by keyboard, in a sensible order,
  with a visible focus indicator, and no traps. See `keyboard-and-focus`.
- **Names & roles**: every control has a programmatic accessible name (label, `aria-label`, or
  associated text) and the right role. Icon-only buttons *must* carry a name.
- **Structure**: real headings in order, landmarks, lists as lists, one `<h1>` intent per view — so
  screen readers can navigate.
- **Text alternatives**: informative images have alt text describing purpose; decorative images are
  hidden from AT.
- **Targets**: interactive targets are comfortably large (aim ≥ 24×24px, ideally ≥ 44×44px on touch).
- **Motion**: honor reduced-motion; nothing critical depends on animation. See `motion-restraint`.
- **Forms**: visible labels (not placeholder-as-label), errors identified in text and tied to the
  field, instructions available before the field.

## Before you finish

1. Walk each requirement above against every screen in the spec — write the a11y note that says so.
2. For each piece of color-coded meaning, confirm a second, non-color signal exists.
3. For each control, confirm it has a name, a role, keyboard operation, and a visible focus state.
4. If any item can't be satisfied, that's a finding — flag it; don't ship under the floor.
