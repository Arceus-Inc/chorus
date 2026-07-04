---
name: states-empty-loading-error
description: How to specify the states a screen spends real time in — empty, loading, partial, error, and success — not just the ideal full-data "happy path" that a mock always shows.
when_to_use: Read for every data-backed view, list, form, or async action. This is the single most-skipped part of a spec. Pairs with interaction-patterns and microcopy-in-ui (what the state actually says).
---

# States: Empty, Loading, Error

A design that only specifies the full-data happy path is unfinished. Real screens spend enormous time
*not* full: brand-new and empty, mid-fetch, half-loaded, failed, or just-succeeded. A fluent model
mocks the ideal state and forgets the rest — so the empty screen looks broken and the error is a raw
stack trace. This skill forces you to design the states users actually see.

## The one rule

**Every async or data-backed view specifies all of its states, not just the full one.** Empty,
loading, error, and success are part of the design — a spec that omits them is incomplete, not "clean".

## The states to design

- **Empty (first-run)**: no data *yet*. Explain what this is, why it's empty, and the one action to
  fill it. This is onboarding, not an error — make it inviting, not blank.
- **Empty (no results)**: a filter/search returned nothing. Say so, and offer a way back (clear
  filters, broaden search) — distinct from first-run empty.
- **Loading**: skeletons over spinners where you know the shape; preserve layout so nothing jumps.
  Optimistic UI where safe. Don't flash a loader for sub-100ms fetches.
- **Partial / paginated**: some data here, more coming — show what you have, indicate there's more.
- **Error**: what failed, in plain language, and what the user can do (retry, go back, contact).
  Never a raw stack trace or a dead end. Preserve the user's input on failure.
- **Success / confirmation**: confirm the action landed (inline, toast) so the user isn't left
  guessing. Prefer undo to an "are you sure?" where feasible.
- **Disabled / permission-denied**: say *why* it's unavailable, not just that it is.

## Before you finish

1. For each data-backed view, write the empty, loading, error, and success states — explicitly.
2. Distinguish first-run empty from no-results empty; they need different copy and actions.
3. Confirm every error tells the user what to *do*, and preserves their input.
4. Confirm loading preserves layout (no content-jump) and success gives feedback.
