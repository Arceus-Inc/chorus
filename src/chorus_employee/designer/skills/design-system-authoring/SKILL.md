---
name: design-system-authoring
description: How to design *within* an existing design system — reuse its tokens, components, and patterns before inventing anything — so a fluent model extends the system instead of quietly forking it.
when_to_use: Read at the START of any design beat, before drafting a single screen, and again before you spawn the design_critic. Use it to design *to* the system, so the critic confirms rather than corrects.
---

# Design-System Authoring

A fluent model will happily produce a screen that *looks* designed and quietly invents a new button
variant, a one-off color, or a bespoke spacing value — each a small fork that erodes the system. This
playbook is the craft that prevents that. It is general know-how; the company's specific system lives
in `DESIGN.md` — always read that first, and when the two disagree, `DESIGN.md` wins.

When the project has **no** `DESIGN.md` yet (or only a thin one), you author or extend it in the
canonical 9-section format — load the `design-md-exemplars` skill, which carries that format and a
vendored library of 58 real-world `DESIGN.md` files (Stripe, Linear, Notion, …) to learn structure and
rigor from. Adapt their shape to this project's brand; never lift their specifics.

## The one rule

**Reuse before you invent.** Every color, space, radius, type ramp, and component you place comes from
the system first. Inventing a new primitive is a last resort that must be justified in the spec — not a
default reached for because it was faster than finding the existing token.

## The reuse ladder (climb it in order)

1. **An existing component** covers this need → use it as-is, cite it by name.
2. **An existing component + documented props** covers it → compose it, don't rebuild it.
3. **Existing tokens compose into it** (a new layout of known primitives) → build it from tokens, note
   the pattern.
4. **Nothing in the system fits** → propose a new primitive *explicitly* in the spec: what it is, why
   the ladder failed, and how it stays consistent with the system's spirit. Flag it for review.

Most needs stop at rung 1 or 2. If you reach rung 4 more than rarely, you are probably skipping a rung.

## What "on-system" means concretely

- **Color**: a token name (`color.surface`, `color.danger`), never a raw hex — unless `DESIGN.md`
  documents an escape hatch.
- **Spacing / sizing**: a step on the documented scale, never an off-scale pixel value.
- **Type**: a named ramp step, never an arbitrary size/weight.
- **Components**: the system's named component, with its documented states and variants.

## Before you finish

1. Walk every value in your spec: is each one a token/component the system names? If not, either map it
   to one or justify the exception on rung 4.
2. Check you didn't rebuild something that exists (a "card", a "modal") under a new name.
3. Confirm any new primitive is called out explicitly for review — never smuggled in.

Do this *up front*. The design_critic is your confirmation, not your editor — a spec that needed the
critic to catch an invented token was designed wrong.
