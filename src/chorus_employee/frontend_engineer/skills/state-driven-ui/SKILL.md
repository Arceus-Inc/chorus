---
name: state-driven-ui
description: How to model an interface as a function of explicit state so it never white-screens — enumerate loading / empty / error / success up front, render from a single state object, and drive every transition through it.
when_to_use: Read for any surface that fetches data, submits, or changes over time. It pairs with es-module-architecture (where the reducer lives) and forms-and-validation (which is a state machine for inputs).
---

# State-Driven UI

The unhappy path is where interfaces break. Code written happy-path-first shows a blank screen while
loading, a broken layout when the list is empty, and an unhandled exception when the request fails. The
fix is to treat the four states as first-class from the start and render the DOM *from* state, never by
poking at it ad hoc.

## The one rule

**The UI is a function of state: `render(state)`. Every state the user can reach — loading, empty,
error, success — is enumerated and has a defined view.**

## Enumerate the states first

- Before wiring anything, list the states the surface can be in. For anything async that's at least:
  `idle`, `loading`, `error`, and `ready` (with `ready` possibly `empty`).
- Give each a real view: a spinner/skeleton for loading, a helpful message + next action for empty, a
  clear recoverable message (with retry) for error, the content for success.

## Render from a single source of truth

- Keep one `state` object. Interactions produce a new state (a reducer / update function), then you call
  `render(state)` to reflect it. Don't scatter `element.style.display` toggles across handlers.
- Make `render` idempotent — calling it twice with the same state yields the same DOM. This keeps
  updates predictable and testable.

## Handle transitions honestly

- Set `loading` *before* the await, clear it in both the success and error branches (a `finally` or
  explicit both-branch handling) so a failed request never leaves a stuck spinner.
- Disable the submit control while in-flight to prevent double-submits; re-enable on completion.
- Never swallow an error into a blank screen. Catch it, move to the `error` state, and show it.

## Before you finish

1. Can you name every state this surface can be in, and does each have a defined view?
2. Is there exactly one state object, with all DOM changes flowing through `render(state)`?
3. Does a failed fetch land in a visible, retryable error state — never a white screen or stuck spinner?
4. Is the empty case (zero results) handled with a message, not a broken layout?
