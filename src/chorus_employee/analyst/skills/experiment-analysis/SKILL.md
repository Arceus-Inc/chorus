---
name: experiment-analysis
description: How to read an A/B test or controlled experiment correctly — check the design before the result, use confidence intervals and effect sizes, resist peeking, and separate a statistically significant lift from one worth shipping. Use whenever interpreting a randomized experiment or comparing a treatment to a control.
when_to_use: Use when the evidence is a randomized experiment / A-B test / holdout — "did the variant win?", "is this lift real?", "can we ship B?". For non-randomized "did X cause Y" data, use causal-inference instead.
---

# Experiment analysis

Randomization is the strongest evidence you get for a causal claim — but only if the design is sound
and the read is honest. A "winning" variant is routinely a peeking artefact, an underpowered flip, or
a trivial lift with a tiny p-value. This skill is the discipline for reading it right.

## When NOT to use this
- The data is observational (no randomization) — use `causal-inference`.
- No control group exists — a before/after is not an experiment; treat it observationally.

## Method

### 1. Interrogate the design before the result
- **Randomization**: were units assigned at random, at the right unit (user, not session, if users
  return)? Check the arms are balanced on pre-period covariates.
- **Power**: was the sample large enough to detect the minimum effect that matters? An underpowered
  test that comes back "no significant difference" has proven nothing.
- **Sample-ratio mismatch (SRM)**: if a 50/50 split arrived 55/45, the assignment or logging is
  broken — stop and fix; the result is untrustworthy.

### 2. Read the effect, not just the p-value
Report the lift as an effect size with a **confidence interval**, absolute and relative. "B lifts
conversion by 0.4pp (95% CI 0.1–0.7pp), a +6% relative change" is a decision input; "p<0.05" is not.

### 3. Resist peeking
Repeatedly checking and stopping when it first looks significant inflates false positives massively.
Fix the horizon in advance, or use a sequential/always-valid method designed for continuous
monitoring. If someone stopped early on a peek, discount the result.

### 4. Statistical vs practical significance
With enough traffic, everything is significant. Tie the effect to the decision: is it large enough,
net of cost/risk, to ship? A significant but trivial lift is a no-ship.

### 5. Guard against experiment-specific traps
- **Novelty / primacy effects** — a shiny change spikes then fades; read a stable window.
- **Multiple metrics / variants** — testing many inflates false positives; pre-declare the primary
  metric and correct for the rest.
- **Segment mining** — "it won for mobile users in Canada" found post hoc is a hypothesis, not a result.
- **Bayesian read** — "probability B beats A" and expected loss can be a more decision-friendly framing
  than null-hypothesis testing; use it when the team reasons in those terms.

## Common failure modes
- Shipping on a peek before the planned horizon.
- Calling an underpowered null "no effect".
- Reporting significance without an effect size or interval.
- Ignoring SRM.
- Harvesting a post-hoc segment win.

## Cross-references
- `statistical-rigor` — intervals, power, multiple comparisons.
- `causal-inference` — for the non-randomized case.
- `findings-communication` — verdict, effect + interval, then the ship/no-ship call.
