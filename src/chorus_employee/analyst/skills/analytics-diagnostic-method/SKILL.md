---
name: analytics-diagnostic-method
description: The spine of any investigation — how a senior analyst gets from "the number changed" to "here is what caused it and what to do". A five-step method (frame the question precisely, build a MECE hypothesis tree, triangulate across independent views, separate signal from noise, present answer-first). Use whenever you must explain why something changed, compare cohorts/funnels, or make a recommendation from data.
when_to_use: Load at the START of any "why did X change / what explains Y / should we do Z" investigation, before reaching for a specialist skill. Skip for pure retrieval ("how many rows?") — just answer that.
---

# Analytics diagnostic method

Dashboards *describe*; they don't *explain*. Getting from "conversions dropped 20%" to "the signup
event stopped firing on Safari after Tuesday's deploy" requires a method, not another chart. This is
the method. It looks slow and is dramatically more accurate than the "run a query, eyeball it, guess"
pattern.

## When NOT to use this

- **Pure retrieval** ("what was revenue last month?"). Compute and answer.
- **The cause is already known** and the user wants help implementing a fix. Don't re-diagnose.
- **Definition questions** ("what does this metric mean?"). Answer directly.

## The five steps

### 1. Frame the question precisely
Restate the vague ask as one exact sentence with a metric, a magnitude, a timeframe, and a segment.
"Traffic dropped" → "Weekly sessions fell from 42k to 28k between the weeks of Apr 14 and Apr 21;
diagnose." A vague question is the #1 cause of a wrong answer. If it can't be made precise, ask ONE
clarifying question — not four — then proceed.

### 2. Build a MECE hypothesis tree
MECE = Mutually Exclusive, Collectively Exhaustive (Minto). Split possible causes so they don't
overlap and none is omitted. A split that almost always works:

```
Observed change in metric M
├── Measurement   — the data is wrong (tracking regression, attribution/UTM shift, bot/filter change)
├── Audience      — who arrives changed (channel mix, new/returning mix, geo/device mix, campaign start/stop)
├── Experience    — what they encountered changed (deploy, performance/errors, content/pricing, 3rd-party outage)
└── External      — the world changed (seasonality, competitor, market/news, platform/policy)
```

**Always check Measurement first** — every other branch is meaningless if the data is wrong, and most
"mystery" changes are measurement regressions. Walk each branch and ask "is there evidence for or
against this?" Don't commit to a hypothesis before ruling out the cheap ones.

### 3. Triangulate before concluding
One metric is one data point. A real diagnosis needs 2–3 independent views that agree:
- **Metric agreement** — sessions, pageviews, and events all dropped proportionally → traffic really
  fell; sessions dropped but events didn't → tracking broke.
- **Source agreement** — two independent sources (warehouse vs logs, tool vs API) tell the same story.
- **Segment agreement** — the move is concentrated in one slice (look there) vs spread across all
  (look for a site-wide / measurement cause).
- **Time-shape agreement** — a cliff (single hour/day) implies a discrete event (deploy/outage); a
  ramp implies a growing issue (filter drift, decay, competitor).

If you only have one view, say so explicitly.

### 4. Separate signal from noise
Before claiming a change is real, check sample size and baseline volatility (see `statistical-rigor`).
A "20% drop" on 50 observations is noise. Compare like-for-like (week-over-week, not Monday-vs-Sunday).
If you sliced 20 ways and one looks significant, weight it down (multiple comparisons).

### 5. Present answer-first (Pyramid Principle)
Verdict in one sentence, then the 2–3 findings that prove it, then what to do, then caveats. If you
can't write the one-sentence verdict, you haven't finished diagnosing — keep going.

## Simpson's paradox (the trap that catches most analysts)
An aggregate trend can *reverse* inside every subgroup. Canonical analytics version: "overall CVR
dropped 5%→4%, but every channel's CVR went up" → a low-CVR channel grew as a share of the mix; the
weighted average fell even though each component improved. **Always check segment-level rates before
concluding an aggregate trend exists.** If the aggregate moves but no segment does, it's a mix shift,
not a performance change — and the fix is completely different.

## Common failure modes
- Starting at the dashboard instead of framing the question.
- Confirming the user's hypothesis instead of testing it against the other branches.
- Skipping the measurement check because "we just shipped, it must be that".
- Reading too much into a tiny segment.
- Refusing to say "I don't know — two causes are consistent with this, I need one more view."

## Cross-references
- `statistical-rigor` — the signal-vs-noise gate this method depends on.
- `causal-inference` — when a branch becomes "X caused Y" and someone will act on it.
- `trend-and-correlation` / `sql-investigation` / `exploratory-data-analysis` — the mechanics of the
  slices this method reasons over.
- `findings-communication` — the Pyramid presentation in step 5.
