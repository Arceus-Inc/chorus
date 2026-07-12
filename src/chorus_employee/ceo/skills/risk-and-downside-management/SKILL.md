---
name: risk-and-downside-management
description: Run a pre-mortem before any material call — name the ways it fails, size the downside, and attach a guardrail or mitigation to each risk. Use before committing to anything hard to reverse.
when_to_use: Use before finalizing any material recommendation or commitment — especially irreversible ones. Every guardrail in a directive should come from this.
---

# Risk and downside management

Optimism is not a strategy. Before you commit, assume the call fails and ask why — then decide whether
the downside is survivable and what guardrail keeps it so. The goal is not to avoid all risk; it is to
take the RIGHT risks with the downside bounded.

## When NOT to use this
- A trivially reversible, low-stakes call. A cheap two-way door doesn't need a full pre-mortem.

## The method
1. **Pre-mortem.** Imagine it's failed. Write the top 2–4 concrete reasons it failed — the specific
   ways, not "it might not work."
2. **Size each risk.** Roughly: how likely, and how bad if it hits? Focus on the high-likelihood or
   high-severity ones; ignore the trivial.
3. **Attach a guardrail per material risk.** A guardrail is a concrete mechanism: a stop-loss metric, a
   staged rollout, a reserve, a reversibility clause, a monitoring signal. Name it specifically.
4. **Check survivability.** Is the worst plausible outcome survivable for the company? If not, the call
   must change — smaller, staged, or not at all — no matter the upside.
5. **Prefer reversibility.** Where you can, structure the commitment so a bad signal lets you back out
   cheaply.

## Rules
- **Name the worst plausible outcome,** explicitly, for every material call.
- **Every material risk has a guardrail** — a specific mechanism, not "we'll watch it."
- **Bounded downside beats unbounded upside.** Never bet the company on any single call.
- **Distinguish risk from uncertainty.** Reducible uncertainty warrants more evidence; irreducible risk
  warrants a guardrail and a decision.

## Common failure modes
- Listing risks with no mitigation attached.
- Sizing by gut and over-weighting the vivid, low-probability tail.
- Betting more than the company can survive losing.

## Cross-references
- `capital-allocation` — the stop-loss that bounds a funded bet.
- `executive-decision-making` — reversibility as a first-class factor in the call.
