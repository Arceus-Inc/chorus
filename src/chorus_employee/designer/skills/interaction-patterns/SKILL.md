---
name: interaction-patterns
description: How to reach for the established interaction pattern (the platform/ARIA convention) for a given job instead of inventing a novel one — so controls behave the way users already expect.
when_to_use: Read when a spec calls for any non-trivial interactive control (menu, tabs, dialog, combobox, tooltip, drag-and-drop, disclosure). Pairs with keyboard-and-focus for the key bindings each pattern requires.
---

# Interaction Patterns

Novel interactions are almost always worse than conventional ones. A fluent model can *invent* a clever
custom control, but users don't want clever — they want the thing to work the way every other app has
taught them it works. This skill is about recognizing the job and reaching for the known pattern.

## The one rule

**Use the established pattern for the job.** Before designing an interaction, name what the user is
trying to do (choose one of many, choose several, reveal detail, confirm a destructive act…) and use
the conventional control for it. Invent only when no pattern fits — and justify it.

## Match the job to the pattern

- **Choose one of a few** → radio group / segmented control. **One of many** → select/combobox.
- **Choose several** → checkboxes / multi-select.
- **On/off now** → toggle switch (applies immediately) vs checkbox (applies on submit) — pick by whether
  it's instant.
- **Switch views in place** → tabs. **Navigate elsewhere** → links/nav, not tabs.
- **Reveal secondary detail** → disclosure/accordion. **Reveal a menu of actions** → menu/dropdown.
- **Focused sub-task / confirm** → modal dialog (used sparingly). **Non-blocking info** → inline or
  toast, not a modal.
- **Destructive action** → confirm step, and prefer undo over a scary confirm where feasible.

## Follow the pattern's contract

Each pattern comes with expected keyboard, focus, and ARIA behavior (WAI-ARIA Authoring Practices).
Using a pattern means honoring its full contract — a "tabs" component that doesn't do arrow-key
navigation and `aria-selected` isn't really tabs. Coordinate with `keyboard-and-focus`.

## Consistency within the product

- Pick *one* way to do a recurring thing and reuse it. Two different date pickers, two different
  confirm styles — that's drift. Check `DESIGN.md` and existing surfaces for the established choice.

## Before you finish

1. For each interaction, name the job and confirm you used the conventional pattern for it.
2. Confirm you honored the pattern's keyboard/focus/ARIA contract, not just its looks.
3. Reserve modals for genuinely blocking sub-tasks; prefer inline/undo elsewhere.
4. Check the product doesn't already solve this a specific way — match it.
