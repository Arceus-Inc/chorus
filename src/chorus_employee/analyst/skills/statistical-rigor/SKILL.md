---
name: statistical-rigor
description: How to tell a real effect from noise, and a statistically significant result from one that matters. Covers sample-size discipline, confidence intervals, base rates, practical vs statistical significance, multiple comparisons, and distribution awareness (mean vs median, outliers). Use before asserting any effect, difference, or "X is high/low".
when_to_use: Use whenever you are about to claim a difference, trend, rate, or comparison is real — "conversions dropped", "A beats B", "this rate is high". Also when a number is computed on few observations, or an average could be distorted by outliers.
---

# Statistical rigor

Most confidently-wrong quantitative claims are noise dressed as signal. This skill is the discipline
that prevents it. Apply it before asserting any effect exists.

## When NOT to use this
- The question is descriptive with no inference ("what was the total?"). Report the number and its `n`.
- The effect is enormous and the sample is huge — still state `n` and the interval, but don't overthink.

## The checks

### 1. Sample size (the first gate)
Rule of thumb for a proportion (95% CI, worst case p=0.5):

| Observations in the smaller group | Margin of error (±) |
|---|---|
| 100 | 10% |
| 400 | 5% |
| 1,000 | 3% |
| 10,000 | 1% |

So a 5%→4% move is noise on 50 obs, weak on 500, real on 5,000. **If the sample is below threshold,
lead with that** — don't quietly quote a comparison over noise. Report `n` beside every rate.

### 2. Confidence intervals, not point estimates
A rate is a range, not a number. Compute and report the interval (`notebook_run`: for a proportion,
`1.96*sqrt(p*(1-p)/n)`; for a mean, use the standard error, or bootstrap when the distribution is
skewed). "CVR is 4.1% (95% CI 3.2–5.0%)" is a claim; "CVR is 4.1%" hides whether it differs from 3.8%.

### 3. Practical vs statistical significance
With enough data, trivial differences become "significant". Always ask: is the effect big enough to
matter for the decision? Report the effect size (absolute and relative) and tie it to the decision,
not just the p-value. A p<0.001 lift of 0.05pp is real and useless.

### 4. Base rates (don't be fooled by the conditional)
A "99% accurate" test for a 1-in-1000 condition flags mostly false positives. Before celebrating a
rate, anchor on the base rate. For predictions, always compare against the naive baseline (majority
class, last value, seasonal average) — a model that can't beat the base rate is degenerate.

### 5. Multiple comparisons
Slice 20 ways and one slice will look "significant" by chance. If you discovered a segment *after*
seeing it move, weight it down or correct for the number of tests. Pre-register what you're testing
when you can.

### 6. Distribution awareness
- Use the **median, not the mean**, for anything heavy-tailed (durations, revenue-per-user, latency);
  one outlier moves a mean by a lot.
- Look at the distribution (`describe()`, a histogram via `chart_render`) before trusting a summary
  statistic. A bimodal distribution has no meaningful "average".
- Watch for day-of-week and seasonality: compare week-over-week or same-day-of-week, never Mon-vs-Sun.

## Common failure modes
- Declaring a trend on a handful of observations.
- Quoting a point estimate with no interval and no `n`.
- Treating statistical significance as importance.
- Reporting a mean for a skewed variable.
- Mining slices and reporting the winner without noting how many you tried.

## Cross-references
- `analytics-diagnostic-method` — step 4 (signal vs noise) is this skill.
- `predictive-modeling` — the baseline and held-out discipline for model claims.
- `experiment-analysis` — CIs, peeking, and significance in the A/B setting.
- `causal-inference` — a real effect still isn't a *cause*.
