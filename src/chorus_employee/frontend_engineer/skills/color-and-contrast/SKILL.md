---
name: color-and-contrast
description: How to keep an interface readable and perceivable — meeting WCAG AA contrast for text and 3:1 for UI components and focus rings, and never encoding meaning in color alone.
when_to_use: Read while writing CSS and choosing colors, and during the accessibility pass. It is the visual half of accessibility; keyboard-and-focus and semantic-html-and-aria cover interaction and structure.
---

# Color & Contrast

Low-contrast text and color-only signals are among the most common accessibility failures, and they're
invisible to someone who isn't looking for them. The floor is objective, so treat it as a hard
requirement you can check, not a matter of taste.

## The one rule

**Text clears WCAG AA contrast, interactive boundaries and focus rings clear 3:1, and no information is
carried by color alone.**

## Contrast ratios

- **Body text**: at least **4.5:1** against its background. **Large text** (≥ 24px, or ≥ 19px bold): at
  least **3:1**.
- **Non-text**: UI component boundaries (input borders, toggle states), meaningful icons, and **focus
  indicators** need **3:1** against adjacent colors.
- Check the actual computed foreground/background pair — including text over images or gradients, which
  is where contrast quietly fails. If it's borderline, darken/lighten until it clears.

## Never rely on color alone

- A required field, an error, a status, a selected item, a link in body text — none should be signaled
  by color only. Add a second cue: text, an icon, an underline, a shape, a pattern.
- Links in running text need a non-color affordance (underline) unless they clear a higher contrast
  bar against surrounding text *and* have another cue.

## Respect the system and the user

- If a `DESIGN.md` exists, take colors from its tokens — they should already encode compliant pairs.
  Don't introduce raw hex values that dodge the system.
- Respect `prefers-reduced-motion` for animation and don't defeat the user's contrast/appearance
  settings.

## Before you finish

1. Does all text meet 4.5:1 (or 3:1 for large text) against its real background?
2. Do focus rings and component borders meet 3:1?
3. Is every state/meaning conveyed by something besides color?
4. Do colors come from the design system's tokens where one exists?
