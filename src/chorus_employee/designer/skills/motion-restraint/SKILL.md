---
name: motion-restraint
description: How to use animation with restraint — motion that communicates (orients, gives feedback, shows continuity) rather than decorates — and always honors reduced-motion preferences.
when_to_use: Read when a spec introduces transitions, animations, or any motion. Pairs with the reduced-motion requirement in wcag-conformance and the feedback role of states-empty-loading-error.
---

# Motion Restraint

Motion is powerful and easy to overuse. A fluent model, asked to make something feel "polished", reaches
for animation everywhere — and the result is slow, distracting, and inaccessible. Good motion is mostly
invisible: it explains what happened. This skill keeps animation earning its keep.

## The one rule

**Motion must communicate, not decorate.** Every animation answers a question — *where did this come
from, what just happened, what's related to what?* If it answers nothing, cut it.

## What motion is *for*

- **Feedback**: confirm an action registered (button press, toggle, item added).
- **Orientation**: show where a thing came from or went (a panel sliding from the edge it lives on).
- **Continuity**: connect two states so the user doesn't lose their place (list reorder, expand).
- **Status**: convey ongoing progress (loading, syncing) — see `states-empty-loading-error`.

## Restraint in practice

- **Fast.** UI transitions are short (~150–250ms typical); longer feels sluggish. The user is trying to
  get somewhere, not watch a show.
- **Purposeful easing.** Ease-out for entering, ease-in for leaving. Avoid bounces/springs unless the
  product's character (per `DESIGN.md`) truly calls for it.
- **Few things move.** Animate the element that changed, not the whole screen.
- **Never block.** Motion must not delay the user's ability to act. No mandatory intro animations.
- **No motion for its own sake.** Parallax, autoplay, gratuitous hover wiggles — cut them.

## Accessibility (non-negotiable)

- Honor **`prefers-reduced-motion`**: provide a reduced/none variant (cross-fade or instant) for every
  non-trivial animation. (WCAG 2.3.3)
- Nothing essential is conveyed *only* by motion — pair it with a static signal.
- No content flashes more than 3×/second (seizure risk). (WCAG 2.3.1)

## Before you finish

1. For each animation, state what it communicates. If nothing, remove it.
2. Confirm durations are short and only the changed element moves.
3. Specify the `prefers-reduced-motion` behavior for every animation.
4. Confirm no motion blocks interaction and nothing flashes rapidly.
