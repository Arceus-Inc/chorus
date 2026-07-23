---
name: token-scale-discipline
description: How to hold the line on design tokens and the spacing/type scale — cite the token, never the raw value — so the design stays on-system and themeable instead of drifting into magic numbers.
when_to_use: Read whenever you place a color, space, size, radius, or type value in a spec, and whenever design_lint flags an off-token color or off-scale spacing. It governs the values; the components skill governs their APIs.
---

# Token & Scale Discipline

Design tokens exist so the system can be themed, re-scaled, and kept consistent from one place. A raw
hex or an off-scale pixel value breaks that promise silently — it renders fine but can never be
re-themed and quietly diverges from every other surface. `design_lint` catches the mechanical cases;
this is the craft behind why.

## The one rule

**Cite the token, never the raw value.** If a value should participate in theming or consistency — and
almost every color, space, and type value should — it is a token reference, not a literal. A raw value
is only acceptable where `DESIGN.md` explicitly documents an escape hatch.

## Colors

- Use semantic token names (`color.text.primary`, `color.surface.raised`, `color.border.subtle`),
  not raw hex and not even primitive palette names where a semantic token exists.
- Semantic over primitive: `color.danger` survives a palette change; `red.600` does not.
- A raw `#rrggbb` in a spec is a smell — map it to the nearest token, or justify the exception.

## Spacing & sizing

- Every gap, padding, and margin is a **step on the scale** (`space.2`, `space.4`), never an arbitrary
  pixel value. The scale is usually a base unit (often 4 or 8px) multiplied — stay on the steps.
- Off-scale values ("13px", "22px") are the single most common drift. They look fine in isolation and
  destroy rhythm across a layout. There is almost always a scale step within a pixel or two — use it.

## Type & radius

- Type is a **named ramp step** (size + line-height + weight bundled), never a loose size. Pairing an
  off-ramp size with an on-ramp line-height is how vertical rhythm breaks.
- Radius, border width, shadow, and z-index are tokens too — the same discipline applies.

## Before you finish

1. Grep your own spec for raw hex and for pixel values that aren't scale steps. Each one is either a
   token you forgot to name or an exception you must justify.
2. Prefer the semantic token over the primitive — you're naming *intent*, not a specific paint.
3. If you truly need an off-scale value, say so explicitly and why — don't let it read as an oversight.
