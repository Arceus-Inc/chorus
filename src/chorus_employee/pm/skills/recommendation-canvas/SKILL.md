---
name: recommendation-canvas
description: The one-page structure for the human-readable recommendation (plan.md) — problem, evidence, the decision, scope, success metric, and revisit trigger — so a reviewer and an engineer can act on it directly. Use when writing the plan that faces the decision.
when_to_use: Use when writing plan.md after the decision is recorded — to give the decision a readable, buildable face that states the choice and cites its evidence.
---

# Recommendation canvas

The recorded decision is the ledger truth; the **plan** is its readable face — what a reviewer judges
and an engineer builds from. A good plan is not a narration of your process; it is a decision, its
evidence, and what to do about it, on one skimmable page.

## When NOT to use this
- The deliverable is the ledger record only (no downstream builder) — then the packet is enough.
- The decision hasn't been recorded yet — record it first; the plan restates it, it doesn't replace it.

## The canvas
Write these sections, in this order, top-down (answer first):

```
# <Title — the bet in a phrase>

## Decision            the chosen option in one decisive line, and why (2–4 sentences), with the
                       cited source URLs / internal refs inline — must match the recorded decision.
## Evidence            the 2–4 claims it rests on, each a fact + its source (product state + web).
## Scope               what to build, concretely — the smallest shippable version first.
## Success metric      the outcome_metric, with a direction, a size, and a window.
## Revisit trigger     what reopens this — the same trigger you recorded.
## Rejected            the 1–2 options you beat, each with the one reason it lost.
```

## Rules
- **Answer first.** The `## Decision` section leads. A reader must know the bet and why from the first
  ten lines, before any scope detail.
- **It must match the ledger.** The option, confidence framing, and cited sources in the plan are the
  same as the recorded decision — never a second, divergent decision hand-written into the plan.
- **Cite inline.** Every evidence claim carries its source right there (a URL, a `repo:` path, a
  `warehouse:` metric), so the reader can check it without leaving the page.
- **Specific and buildable, not open questions.** "We will ship X with scope A, B, C" — not "we should
  explore whether X might help". If it reads as a list of unknowns, you haven't decided.
- **Smallest shippable first.** Scope the minimum that tests the bet; defer the fuller build behind the
  metric. A plan that ships everything ships nothing on time.
- **One page.** If the reader won't finish it, it failed. Cut the intermediate reasoning; keep the
  decision and the evidence that earns it.
