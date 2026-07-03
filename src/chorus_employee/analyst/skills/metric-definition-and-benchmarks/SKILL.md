---
name: metric-definition-and-benchmarks
description: How to answer "is this number good, bad, or just noise?" correctly — pin the metric's exact definition and denominator, check the sample supports a verdict, compare only to a like-for-like reference, and treat benchmarks as descriptions of a population, never as targets. Use whenever asked to judge a metric's health.
when_to_use: Use when asked "is X good / normal / high / low", when a rate is quoted without a denominator, or when comparing a number to a benchmark. Pairs with statistical-rigor for the noise check.
---

# Metric definition and benchmarks

Most wrong answers to "is this number good?" come from three mistakes: comparing to a benchmark that
measures something else, quoting a benchmark as a target, or judging a number that is actually noise.
This skill is the discipline for a defensible verdict.

## When NOT to use this
- Pure retrieval of the number (no judgement asked).
- The number is clearly noise (too few observations) — send it back through `statistical-rigor` first.

## Method

### 1. Pin the definition
The same word means different things across systems. Before judging, state exactly how the metric is
computed here: what event, what window, included/excluded cases. A metric compared across two
definitions is a category error (a redefined metric is not comparable to its old self).

### 2. Pin the denominator
Most rate disputes are denominator disputes. "Conversion rate" over *all* sessions mixes intent-free
and intent-heavy traffic; compute it at the point of intent. Always state numerator ÷ denominator
explicitly before comparing.

### 3. Check the sample supports a verdict
A benchmark comparison on a noise-level sample is meaningless. If `n` is below the detection floor
(see `statistical-rigor`), lead with that and refuse a confident verdict.

### 4. Compare like-for-like
Only compare to a reference from the same population, definition, and period. Name the source, its
year, its population, and its `n`. If you can't find a matching reference, say the comparison is
directional, not exact — don't force a false-precision benchmark.

### 5. Benchmarks describe, they don't prescribe
A benchmark is where a population sits, not where *this* number *should* be. Below-benchmark can be
healthy given the surrounding unit economics; above-benchmark can be unprofitable. Tie the verdict to
the actual objective, not to matching a population average.

### 6. Watch the traps
- A metric moving for a reason outside what it measures (an instrumentation change inflating it).
- Attribution model silently deciding the answer (last-click vs multi-touch).
- Mix shifts masquerading as trend changes (see Simpson's paradox in `analytics-diagnostic-method`).
- A metric in isolation that only means something as a ratio (a cost without the value it buys).

## Verdict form
> Your X is [value] (n=…). A like-for-like reference is [Z, from source/year/population]. Your number
> is [above/at/below] by [W], which [does/doesn't] matter because [tie to the objective]. Caveat: […].

## Common failure modes
- Quoting a cross-population average as if it applied here.
- Judging a rate without stating its denominator.
- Giving a verdict on noise.
- Treating a benchmark as a target.

## Cross-references
- `statistical-rigor` — the sample-size gate this depends on.
- `analytics-diagnostic-method` — mix shifts and the framing discipline.
- `findings-communication` — deliver the verdict answer-first with its caveat.
