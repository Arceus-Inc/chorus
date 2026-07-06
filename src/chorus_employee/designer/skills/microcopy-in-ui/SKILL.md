---
name: microcopy-in-ui
description: How to write the words *inside* the UI — labels, buttons, empty states, errors, tooltips, confirmations — so they're clear, specific, action-oriented, and consistent, because copy is part of the design.
when_to_use: "Read whenever a spec contains user-facing text — button labels, form labels, error messages, empty states, confirmations, tooltips. Pairs with states-empty-loading-error (which states need copy) and interaction-patterns."
---

# Microcopy in UI

Interface copy is design, not filler — a vague button label or a cryptic error breaks a screen as
surely as a broken layout. A fluent model tends to write generic UI text ("Submit", "Error", "Are you
sure?") that technically fits but doesn't help. This skill is about words that do work.

## The one rule

**Say what it does, specifically, in the user's words.** A label or button names the concrete outcome
("Save changes", "Delete 3 files"), not a generic verb ("Submit", "OK"). Specificity is clarity.

## Buttons & actions

- Label the **outcome**, not the mechanism: "Create project", not "Submit". "Delete account", not "OK".
- Match the label to the action's weight — destructive buttons say the destructive thing.
- In a confirm dialog, buttons name the choices ("Delete" / "Keep") — never a bare "Yes" / "No" that
  forces the user to re-read the question.

## Labels & instructions

- Form labels are **visible** and describe the field plainly (not placeholder-as-label — placeholders
  vanish on focus and fail accessibility). See `wcag-conformance`.
- Put instructions *before* the field, and keep them short. Show format hints ("MM/YYYY") where helpful.

## Errors

- Say **what went wrong and what to do**: "Email already in use — sign in instead?" beats "Invalid
  input." Be specific, be human, don't blame the user.
- Never expose codes/stack traces to end users. Tie the message to the field. See
  `states-empty-loading-error`.

## Empty states & confirmations

- Empty states explain and invite: what this is + the one action to fill it (see
  `states-empty-loading-error`).
- Confirmations state the consequence and are dismissible; success messages confirm plainly.

## Voice & consistency

- Match the product's voice — but favor **clear over clever**. When in doubt, be plain.
- One term per concept across the whole UI (don't mix "folder"/"directory", "delete"/"remove"). Check
  `DESIGN.md` and existing surfaces for the established vocabulary.
- Sentence case usually reads friendlier than Title Case for UI — follow `DESIGN.md`.

## Before you finish

1. Replace every generic label ("Submit", "OK", "Error") with a specific one.
2. Confirm form fields have visible labels, not placeholder-only.
3. Confirm each error says what happened *and* what to do, in plain language.
4. Check one term per concept across the spec, and the voice matches the product.
