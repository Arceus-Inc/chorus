---
name: causal-inference
description: How to decide whether X actually caused Y, or whether the correlation is coincidental, confounded, or reversed — and when to refuse a causal claim. Applies confounder reasoning and the Bradford Hill viewpoints as a scorecard before any decision (rollback, ship, kill, double-down) is recommended from observational data.
when_to_use: Use whenever someone is about to ACT on a correlation from observational (non-randomized) data — "X dropped after we shipped Y, should we revert?", "did the new onboarding cause retention to rise?". If the evidence is from a proper randomized A/B test, use experiment-analysis instead.
---

# Causal inference

Observational data is full of correlations that look causal and aren't. A deploy ships Tuesday, a
metric moves Wednesday, and the instinct is to revert. Sometimes the deploy did it; sometimes a
campaign landed the same day; sometimes Wednesday is always like that. This skill is the discipline
for separating causation from association *before* recommending an action.

## When NOT to use this
- The evidence is a properly randomized experiment — randomization handles most of this; use
  `experiment-analysis`.
- The user is only brainstorming hypotheses, nowhere near a decision — build the tree with
  `analytics-diagnostic-method` first.
- The move is inside the noise floor — there's nothing to explain yet (`statistical-rigor`).

## Method

### 1. State the claim precisely
Write it as one sentence: "**X caused Y**, X = [specific change], Y = [specific metric move, magnitude,
period]." Then the counterfactual: "if X had not happened, would Y still have moved?" Most of the
checks below are ways of probing that counterfactual.

### 2. Rule out the three cheap killers
- **Reverse causation** — could Y have caused X, or both be driven by a third thing?
- **Confounding** — is there a common cause Z that moved both X and Y? (A campaign that shipped the
  same day as the deploy and also changed the traffic mix.) List candidate confounders explicitly.
- **Selection / mix shift** — did the *population* change so the aggregate moved with no unit changing
  (Simpson's paradox)? Check segment-level rates.

### 3. Score the Bradford Hill viewpoints
For each, mark pass / partial / fail with a one-line justification:

| # | Viewpoint | Passes when… |
|---|---|---|
| 1 | Strength | the move is several × the metric's normal day-to-day variance |
| 2 | Consistency | the effect appears in ≥3 independent slices (browser/geo/device/time), not one |
| 3 | Specificity | Y moved but neighbouring metrics that *shouldn't* have didn't |
| 4 | **Temporality** | Y's move starts *after* X — **non-negotiable** |
| 5 | Dose-response | heavier-exposed cohorts show a larger move than lighter-exposed |
| 6 | Plausibility | you can name the concrete mechanism (the specific code/UX path) |
| 7 | Coherence | adjacent metrics tell a consistent story; nothing contradicts it |
| 8 | Experiment | a randomized split, holdout, or staged rollback confirms it |
| 9 | Analogy | similar changes produced similar effects before |

Temporality is a gate: if Y moved *before* X, the claim is dead regardless of the other scores.

### 4. Verdict and the refusal rule
- **≥5 passes including temporality** → well-supported; recommend the action, flag residual uncertainty.
- **3–4** → tentative; lean toward action but propose a confirming intervention (holdout, staged rollback).
- **≤2** → weak; **refuse the recommendation** and name exactly what evidence to gather next.

The refusal is the load-bearing part. Recommending a rollback on one chart and a hunch causes
incidents. When evidence is weak, the correct answer is not "yes" or "no" — it is "the evidence is
weak; here is what I'd check first."

## Common failure modes
- Skipping temporality (assuming X preceded Y because the user said so — read the timestamps).
- Calling plausibility "pass" because *some* mechanism could exist; it must be specific and grounded.
- Ignoring the confounder that shipped the same day.
- Recommending an action anyway when only 1–2 viewpoints pass.

## Cross-references
- `analytics-diagnostic-method` — builds the hypothesis tree this scores.
- `statistical-rigor` — the strength/consistency checks depend on it.
- `experiment-analysis` — if it was randomized, use that instead.
