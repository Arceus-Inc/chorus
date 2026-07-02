---
name: findings-communication
description: How to present an analysis so a decision-maker can act on it — the Pyramid Principle (answer first, then the evidence that proves it, then caveats), quantify every claim, and name uncertainty honestly. Use when writing up any finding, recommendation, or brief.
when_to_use: Use when writing the final deliverable of any investigation — a findings doc, a recommendation, or a brief. Apply it to structure the write-up regardless of the domain.
---

# Findings communication

An analysis nobody can act on is wasted work. Decision-makers read top-down and lose patience with a
build-up. Lead with the answer; make every claim a number with a source; be honest about what you
don't know. This skill is how a distinguished analyst presents.

## When NOT to use this
- The task is a raw data dump explicitly requested as such.

## The structure (Pyramid Principle)

Answer first, reasoning second, data third — the opposite of how most drafts are written.

```
VERDICT (one sentence): what is true / what to do.
SUPPORTING FINDINGS (2–4 bullets): each is one claim + the one number that proves it + its source.
WHAT TO DO NEXT (when a decision is implied): actions ranked by impact.
CAVEATS: sample-size, measurement, and assumption limits; what would change the conclusion.
```

If you cannot write the one-sentence verdict, the analysis isn't finished — keep going, don't publish.

## Rules
- **Quantify.** Every factual claim carries the exact number you computed or found, and (for external
  facts) the source URL. "Signups rose sharply" is not a finding; "signups rose 38% (412→570/wk)" is.
- **Answer the whole question.** Address every part the task asked; a missing part fails the work.
- **Name uncertainty.** State confidence intervals, `n`, and assumptions. "I can't distinguish these
  two causes without one more slice" is a real, respectable answer; false certainty is not.
- **No process theatre.** Report the conclusion and its evidence, not a narration of which tools you
  ran. The reader wants the answer and why to believe it.
- **Self-consistency.** Numbers in the summary must match the body; dates must be real (never future);
  a ranking must agree with the figures it's built from. Re-read for contradictions before finishing.
- **Right altitude.** Give the decision-maker what changes the decision, not every intermediate table.

## Common failure modes
- Burying the answer under the methodology.
- Vague qualitative claims with no number.
- Omitting caveats, projecting false certainty.
- Summary that contradicts the body (or an impossible/future date).
- Answering some of the question and leaving parts unaddressed.

## Cross-references
- `analytics-diagnostic-method` — step 5 is this structure.
- `statistical-rigor` — the intervals and `n` that make a claim honest.
- Every other skill ends here: the deliverable is judged on how well it communicates a defensible answer.
