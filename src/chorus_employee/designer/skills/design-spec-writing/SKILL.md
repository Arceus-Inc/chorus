---
name: design-spec-writing
description: How to write the design_spec.md deliverable so it's buildable — concrete tokens, component references, states, layout, and accessibility notes an engineer can implement without guessing — instead of vague vibes.
when_to_use: Read whenever you produce the design_spec.md deliverable. This is the shape the Definition of Done checks for; it ties together every other design skill into the handed-off artifact.
---

# Design-Spec Writing

The Designer's deliverable is a `design_spec.md` an engineer builds from — not a mood board and not a
picture. A fluent model tends to write evocative but unbuildable prose ("a clean, modern settings
page") that leaves every real decision to the implementer. This skill is about writing a spec that is
*specific enough to build* and *complete enough to pass the gate*.

## The one rule

**Write it so an engineer can build it without asking you a question.** Every value is concrete (a
named token, a scale step, a component), every state is covered, every accessibility requirement is
stated. If a reader would have to guess, the spec isn't done.

## What the spec must contain

- **Overview**: what this surface is, who uses it, the primary task and primary action. One or two
  paragraphs — anchor the reader (draws on `user-flow-mapping`, `visual-hierarchy`).
- **Layout & hierarchy**: structure at the relevant breakpoints, what's primary/secondary, grouping —
  concrete, not "responsive and clean" (see `responsive-layout`, `information-density`).
- **Tokens**: the actual tokens used — colors, spacing steps, type ramp, radii — by name, not raw
  values (see `token-scale-discipline`). No off-token color or off-scale spacing.
- **Components**: each component referenced by its system name, with the variant/props and the states
  it must render (see `component-api-design`, `design-system-authoring`).
- **States**: empty, loading, error, and success for every data-backed part — spelled out (see
  `states-empty-loading-error`). This is the most-skipped and most-checked section.
- **Accessibility**: an explicit section — contrast met, keyboard path, focus order, names/roles,
  reduced-motion, targets (see `wcag-conformance`). Not "it's accessible" — *how*.
- **Copy**: the actual labels, button text, empty/error messages (see `microcopy-in-ui`).
- **Interactions/motion**: patterns and any animation, with reduced-motion behavior (see
  `interaction-patterns`, `motion-restraint`).

## Style

- **Concrete over evocative.** "16px (`space.4`) gap, `color.border.subtle` 1px divider" beats "nicely
  separated". Adjectives don't build.
- **Structured.** Headings and lists an implementer can check off — the DoD looks for tokens/components,
  states, and accessibility sections by structure.
- **Sufficient length, no padding.** Cover every section with substance; don't hit a word count with
  filler. The gate checks for real content, not volume.

## Before you finish

1. Read the spec as the engineer: is there any decision left unspecified? Fill it.
2. Confirm every required section is present — especially states and accessibility (the checked ones).
3. Confirm every value is a token/component name, and run `design_lint` over any token block.
4. Confirm the copy is written out, not described.
