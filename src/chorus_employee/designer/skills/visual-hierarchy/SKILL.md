---
name: visual-hierarchy
description: How to make a screen's structure legible at a glance — one primary action, deliberate emphasis, generous grouping and whitespace — so the eye is led instead of overwhelmed.
when_to_use: Read when laying out any screen or composing a view from components. Pairs with information-density (how much to show) and responsive-layout (how it reflows).
---

# Visual Hierarchy

A screen where everything is emphasized has no hierarchy — the user's eye has nowhere to land. A fluent
model tends to give every element equal visual weight because each one *seems* important in isolation.
Hierarchy is the deliberate act of making some things loud and most things quiet.

## The one rule

**One primary action per view.** Exactly one element should be the loudest thing on the screen — the
obvious next step. Everything else is secondary or tertiary. If you have two primaries, you have none.

## The tools of emphasis (spend them sparingly)

- **Size & weight**: bigger/bolder reads as more important. A clear type ramp does most of the work.
- **Color**: reserve your strongest/brand color for the primary action and true alerts. Color spent
  everywhere buys nothing.
- **Space**: whitespace *is* emphasis — isolation draws the eye more reliably than decoration.
- **Position**: top-left / top-center (in LTR) and the natural reading path get seen first.

Emphasis is a budget. Every element you make loud makes every other loud element quieter.

## Grouping & rhythm

- **Proximity**: related things sit close; unrelated things get space between them. Grouping by
  distance beats grouping by boxes and borders.
- **Alignment**: a consistent grid and alignment create calm; ragged edges read as noise.
- **Consistent spacing steps** (see `token-scale-discipline`) create rhythm; random gaps break it.

## Scanning

- Users scan, they don't read. Structure for the scan: clear headings, short labels, a visible primary
  path. The three-second test: can a new user find the main action in three seconds?

## Before you finish

1. Point to the single primary action. If you can't, or there's more than one, fix it.
2. Squint at the layout (blur it): does the important stuff still stand out? If it's a uniform gray
   field, there's no hierarchy.
3. Check that related controls are grouped by proximity and aligned to the grid.
4. Confirm you didn't spend the strong color / bold weight on secondary elements.
