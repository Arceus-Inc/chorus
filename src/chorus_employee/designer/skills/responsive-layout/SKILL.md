---
name: responsive-layout
description: How to specify a layout that holds from small to large viewports — mobile-first, fluid grids, sensible breakpoints, and reflow that never requires horizontal scrolling — instead of one fixed width.
when_to_use: Read when laying out any screen that will be viewed across device sizes. Pairs with visual-hierarchy (structure) and the WCAG reflow requirement in wcag-conformance.
---

# Responsive Layout

A layout designed at one width breaks at every other width. A fluent model tends to describe "the
screen" as a single fixed composition and forgets that the same content must survive a phone, a
tablet, a laptop, and a zoomed-in browser. Responsive design is specifying how the layout *adapts*.

## The one rule

**Design mobile-first, then let content earn the space.** Start from the narrowest viewport where
priorities are forced clear, then add columns and breathing room as width allows — don't design a
desktop layout and cram it down.

## Fluid over fixed

- Prefer **fluid** sizing (percent, `fr`, `min()/max()/clamp()`, flex/grid auto-fit) over fixed pixel
  widths. Fixed widths are the root of most breakage.
- Constrain readable text to a comfortable measure (~45–75 characters) — full-width body text on a wide
  screen is as bad as cramped text on a narrow one.

## Breakpoints

- Add a breakpoint **where the content breaks**, not at device-branded widths. Let the design tell you
  where it stops looking right.
- Keep them few. Each breakpoint is a layout to specify, test, and maintain.
- Define what changes at each: column count, nav pattern (inline → drawer), spacing step, font ramp.

## Reflow (accessibility)

- Content must reflow to a **320px-equivalent** width (and up to 400% zoom) **without horizontal
  scrolling** for the main content. (WCAG 1.4.10) This is a floor, not a nicety.
- Nothing critical hidden only behind hover (no hover on touch) — provide a tap/click path.

## Touch vs pointer

- Touch targets are comfortably large and spaced (see `wcag-conformance`); don't ship desktop-dense
  click targets to a phone layout.

## Before you finish

1. Describe the layout at (at least) a narrow and a wide viewport, plus what changes between them.
2. Confirm no fixed width forces horizontal scroll at 320px / 400% zoom.
3. Confirm text measure stays readable at the widest breakpoint.
4. Confirm nav and interactive elements have a touch-friendly form on small screens.
