---
name: evidence-brief
description: How to assemble the cited evidence a product decision rests on — the two first-class inputs (product state and the outside world), each claim a fact + a source + a confidence, with gaps named honestly. Use before you weigh options or record a decision.
when_to_use: Use at the start of any decision, before generating options — to gather and structure the evidence, and again to check a decision is grounded before recording it.
---

# Evidence brief

A decision that cites no evidence is not shippable — it is a guess with a confident voice. Before you
weigh options, assemble the evidence; before you record a decision, check it clears the bar. A PM
decides from two first-class sources, not one:

1. **Product state (internal, read this first).** What exists and how it performs *today*: the codebase
   (`repo_search` — what's shipped, is the change feasible?) and the warehouse (`warehouse_query` — the
   usage/funnel metric that says whether this is the real gap). Ground *"can we build it, and is this
   actually the gap?"*
2. **The outside world (external).** A current, credible source on how others solve this and what users
   expect (`web_search` + `web_extract`, or the `researcher` subagent for a real sweep). Ground *"is
   this worth building, for whom, and how badly?"*

## When NOT to use this
- The evidence was already handed to you and is sufficient and cited — don't re-gather; go decide.
- A trivial, reversible call where the cost of being wrong is lower than the cost of the research.

## The shape of a claim
Every claim in the brief is three things — never a bare assertion:

```
CLAIM      one fact, stated plainly and specifically
SOURCE     where it came from: a repo path (repo:app/x.py), a metric (warehouse:run_metrics), or a URL
CONFIDENCE 0..1 — how strongly the source actually supports the claim
```

"Users want visibility" is not a claim. "Completion is flat at 0.62 while stuck-tickets rose 41→58/wk
(warehouse:run_metrics, 0.9)" is.

## Rules
- **Cover both inputs.** A brief that cites only the web, or only internal metrics, is half-grounded.
  Name which of the two questions each claim answers.
- **Cite, don't paraphrase from memory.** A market/user/competitor claim without a `source_url` is
  fabricated until proven otherwise. If you couldn't verify it, it is a GAP, not a claim.
- **Name the gaps.** List what you could *not* establish and why. An honest gap ("no data on churn by
  segment") is worth more than a made-up number — it tells the decider where the risk is.
- **One sweep, then stop.** Gather enough to decide, not everything knowable. A couple of targeted
  reads and one focused external question is usually enough; don't research until the beat times out.
- **Quantify.** Prefer the exact number over the adjective. Rank claims by how much they move the call.

## The output
A short, skimmable brief: the QUESTION, the EVIDENCE (claims as above, grouped by the two inputs), the
GAPS, and — if one jumps out — the NEW ANGLE the evidence surfaced. This is what the options are weighed
against and what the decision's `claims` are drawn from.
