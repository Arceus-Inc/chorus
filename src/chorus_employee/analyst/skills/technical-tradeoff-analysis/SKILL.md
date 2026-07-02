---
name: technical-tradeoff-analysis
description: How to analyze a hard technical or strategic decision the way a distinguished engineer does — reason from first principles, quantify the option space with back-of-the-envelope estimates, reason about failure modes and scale, and land a defensible recommendation with its assumptions and caveats. Use for architecture/design/technology-choice and "which should we do" questions.
when_to_use: Use for high-level technical or strategic decisions — "which datastore / architecture / approach should we use", "will this scale", "is this design sound", "what are the tradeoffs of X vs Y". Not for routine data pulls.
---

# Technical tradeoff analysis

A distinguished engineer's edge is not more opinions — it is reasoning from first principles,
quantifying the option space, and being explicit about assumptions and failure modes. This skill is
that discipline for a hard technical or strategic decision.

## When NOT to use this
- A routine factual/data question — just answer it.
- The decision is already made and only execution remains.

## Method

### 1. Frame the decision and the constraints
State the actual decision, the options under consideration, and the criteria that matter (latency,
cost, correctness, operability, time-to-build, blast radius). Surface the hard constraints and the
success/failure thresholds. A decision without stated criteria produces an unfalsifiable opinion.

### 2. Reason from first principles
Derive the answer from fundamentals rather than cargo-culting a popular choice. What does the workload
actually demand — read/write ratio, consistency needs, data shape, access patterns, growth curve?
Strip the problem to its invariants before comparing named technologies.

### 3. Quantify with back-of-the-envelope estimates
Put numbers on it before opining. Estimate throughput, data volume, QPS, latency budgets, storage, and
cost at both current and 10–100× scale. Useful anchors: Little's Law (concurrency = arrival rate ×
latency), rough latency ladder (memory ns, SSD µs, network ms, cross-region tens of ms), and cost per
unit at volume. Show the arithmetic. An order-of-magnitude estimate settles most debates; state the
assumptions behind each figure so they can be challenged.

### 4. Compare options against the criteria
Build a small tradeoff matrix: options × criteria, each cell a concrete claim (ideally a number), not
a vibe. Name what each option is *best* and *worst* at. Reject false binaries — often a hybrid or a
staged path dominates.

### 5. Reason about failure modes and scale
For the leading option, ask what breaks first as load grows, what the failure looks like, and how it's
detected and mitigated. Consider operability (who runs it, on-call cost), migration/rollback, and the
one-way vs two-way-door nature of the decision. A cheap reversible choice deserves less deliberation
than an irreversible one.

### 6. Recommend with assumptions and caveats
Give a clear recommendation and *why it wins on the stated criteria* — then the assumptions it rests
on, the conditions under which you'd choose differently, and what to measure to confirm. A
distinguished recommendation is falsifiable: it says what would change its mind.

## Common failure modes
- Opinion with no numbers — never estimating scale, cost, or latency.
- Picking the popular/default option without deriving fit from the workload.
- Ignoring operability and failure modes (the "works in the demo" trap).
- Treating a two-way-door (reversible) decision as if it were irreversible, or vice versa.
- A recommendation that can't state what would falsify it.

## Cross-references
- `statistical-rigor` — put intervals on estimates; distinguish signal from noise in benchmarks.
- `web-research` — source real numbers (limits, benchmarks, pricing) and cite them.
- `findings-communication` — recommendation first, tradeoff matrix, then assumptions and caveats.
