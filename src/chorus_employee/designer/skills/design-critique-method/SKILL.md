---
name: design-critique-method
description: How to critique a design against principles and the design system — the self-review you run before spawning the design_critic — grounded in evidence (design_lint, DESIGN.md, WCAG) rather than taste.
when_to_use: Read before you consider a design done, and it is the method the design_critic subagent applies. Use it to catch your own findings first, so the critic confirms rather than corrects.
---

# Design-Critique Method

The difference between a design that ships and one that gets sent back is whether it was *critiqued*
before hand-off. A fluent model is a poor judge of its own work — it wrote the screen, so it reads it
charitably. This skill is the structured, evidence-based self-review that catches problems while
they're cheap to fix. It's also exactly what the `design_critic` subagent does — run it on yourself
first.

## The one rule

**Ground every judgment in evidence, not taste.** A critique finding cites the rule it breaks — a
`design_lint` result, a `DESIGN.md` token/component, a WCAG threshold, a named principle — not "I don't
like it". If you can't name the rule, it isn't a finding.

## Run the passes in order

1. **System conformance** (`design-system-authoring`, `token-scale-discipline`): every color/space/type
   a token? every component from the system? any invented primitive justified? Run `design_lint` and
   treat its findings as must-fix.
2. **Accessibility floor** (`wcag-conformance`, `color-contrast`, `keyboard-and-focus`): contrast ratios
   met, keyboard operable, focus visible, names/roles present, color never alone. These are gates.
3. **State completeness** (`states-empty-loading-error`): are empty/loading/error/success specified, not
   just the happy path?
4. **Hierarchy & clarity** (`visual-hierarchy`, `information-density`): one primary action? scannable?
   nothing over-dense or over-decorated?
5. **Interaction & flow** (`interaction-patterns`, `user-flow-mapping`): conventional patterns? a way
   back from every screen? unhappy paths designed?
6. **Copy** (`microcopy-in-ui`): specific labels, helpful errors, consistent vocabulary?

## How to write a finding

- **Element + rule + fix**: *"The secondary button uses `#6b7280` on white (2.9:1) — below the 4.5:1
  floor (WCAG 1.4.3). Use `color.text.secondary` which passes."* Concrete, cited, actionable.
- Separate **must-fix** (system/accessibility gates) from **should-improve** (hierarchy, polish). Don't
  bury a contrast failure among nits.

## The verdict

- **PASS** only when every must-fix pass is clean. Any unresolved gate → **FAIL** with the findings.
- A PASS with no evidence is not a PASS — say *what* you checked and how it cleared.

## Before you finish

1. Run all six passes; write findings as element + rule + fix.
2. Run `design_lint` and fold its results into pass 1 — don't PASS over an open lint finding.
3. Sort findings must-fix vs should-improve; resolve every must-fix before hand-off.
4. State the verdict and the evidence behind it.
