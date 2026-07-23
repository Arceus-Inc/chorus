---
name: information-density
description: How to decide how much to show — progressive disclosure, defaults over options, and cutting secondary content — so a screen carries the right amount of information instead of everything at once.
when_to_use: Read when a screen risks becoming cluttered (dashboards, settings, tables, forms with many fields). Pairs with visual-hierarchy (what's loud) and states-empty-loading-error (what shows when there's little data).
---

# Information Density

The default failure mode of a capable model is *too much*: every field, every option, every stat, all
on one screen, because each one is individually justifiable. But a screen's job is to let the user do
the task in front of them — not to expose the entire data model. Density is the craft of deciding what
earns its place.

## The one rule

**Show what the task needs now; defer the rest.** Every element must earn its place against the primary
task of the view. If it serves a secondary or rare need, it moves behind progressive disclosure — it
doesn't get cut from existence, it gets cut from *this glance*.

## Progressive disclosure

- **Primary now, secondary on demand.** Common path visible; advanced/rare controls behind "More",
  an accordion, a detail drawer, or a secondary screen.
- **Summary → detail.** Show the summary; let the user drill in. A table shows key columns; the row
  expands or links to the full record.
- **Defaults over options.** A good default removes a decision. Ship the sensible default and let the
  minority who need to change it go find the setting — don't put the setting in everyone's face.

## Cutting

- For each element ask: *does the user need this to complete the task on this screen?* If "not now",
  defer it. If "not really", cut it.
- Beware feature-count-driven layout — the number of features is not the number of things on screen.
- Empty space is not wasted space; it's what makes the kept content legible (see `visual-hierarchy`).

## When density is genuinely required

- Some tools (trading, monitoring, data grids) are legitimately dense. Then density is a *design
  target*: tight, consistent spacing steps, strong alignment, restrained color, clear grouping — dense
  *and* ordered, not dense *and* chaotic. Consult `DESIGN.md` for the product's density expectations.

## Before you finish

1. List everything on the screen; mark each primary / secondary / rare. Defer secondary and rare.
2. For each option, ask whether a default would remove it. If yes, default it.
3. Confirm the primary task is completable without expanding anything.
4. If the screen is intentionally dense, confirm it's *ordered* dense, not cluttered.
