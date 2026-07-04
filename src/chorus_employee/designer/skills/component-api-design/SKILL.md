---
name: component-api-design
description: How to design a component's *interface* — its props, variants, states, and slots — so it composes into the system, stays minimal, and can't be misused, instead of accreting boolean flags.
when_to_use: Read when a spec introduces or extends a reusable component (not a one-off screen). Pairs with design-system-authoring (reuse first) — this governs the shape of anything you legitimately do build.
---

# Component API Design

A component is an API, not a picture. Its props are the contract every future screen depends on, and a
sloppy contract (a pile of booleans, overlapping variants, states that can contradict) spreads misuse
across the whole product. Design the interface with the same care as a function signature.

## The one rule

**Model variants and states as closed sets, not open booleans.** A `variant: "primary" | "secondary" |
"danger"` can't express an illegal combination; three booleans (`isPrimary`, `isDanger`, `isGhost`) can
express eight, most of them nonsense. Constrain the API so the wrong thing is unrepresentable.

## Props: the contract

- **Minimal surface.** Every prop is a maintenance and misuse cost. If two props are always set
  together, they're one prop. If a prop is never actually varied, it's a constant — drop it.
- **Variant enums over boolean piles.** One `variant`/`size`/`tone` enum beats a spray of flags.
- **Sensible defaults.** The common case should need almost no props. Defaults encode the house style.
- **Name for intent, not implementation.** `tone="danger"`, not `color="red"`.

## States: enumerate them, all of them

Every interactive component must define its full state set, not just the happy resting state:

- default, hover, focus(-visible), active, disabled, loading, selected, error — as applicable.
- These are covered in depth by the `states-empty-loading-error` and `keyboard-and-focus` skills; a
  component API is incomplete until each relevant state is specified.

## Composition & slots

- Prefer **slots/children** over a prop for every piece of content. A `Card` with a `header` slot
  outlives a `Card` with `titleText`, `titleIcon`, `titleBadge`… props.
- Compose from existing primitives (design-system-authoring rung 2–3) rather than growing one mega-
  component with a mode for everything.

## Before you finish

1. Can the API express an illegal state? Tighten it into an enum or split the component.
2. Is every prop actually varied by a real caller? Cut the ones that aren't.
3. Is every interactive state enumerated with its tokens? An unspecified state ships as an accident.
4. Could a slot replace a content prop? Usually yes — prefer it.
