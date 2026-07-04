---
name: decision-record
description: How to write the decision of record — an immutable, ADR-style bet with its rationale, confidence, the metric that should move, a revisit trigger, cited claims, and the alternatives it beat. Use when calling record_decision, the moment you commit.
when_to_use: Use at the moment of commitment, when you call the record_decision tool — to make the recorded decision complete, honest, and auditable rather than a bare option string.
---

# Decision record

The PM's signature deliverable is not a document — it is a **recorded decision**: an immutable, cited,
ADR-style bet the org can act on and later hold to account. `record_decision` writes it to the ledger;
this skill is how to fill it so the record is worth trusting.

## When NOT to use this
- The evidence hasn't cleared the confidence floor — go gather evidence first (see `evidence-brief`),
  or escalate. Do not record a low-confidence, uncited decision "to make progress".
- You are only revising execution details of an already-recorded decision — that's the plan, not a new
  record.

## The fields, and how to fill each
```
option               the bet, in one decisive line — a mechanism, not a wish ("build X", not "improve trust")
rationale            WHY this over the others — decisive prose that names the evidence and the tradeoff
confidence           0..1, honestly — your calibrated belief, not a number chosen to clear the floor
outcome_metric       the ONE metric that should move if you're right, with a direction and rough size
revisit_trigger      what would reopen this: "if <metric> is flat within <window>, revisit" — testable
rejected_alternatives each real option you beat, with the specific reason it lost (from options-set-generator)
claims               the cited facts it rests on — each a text + source_url + confidence (from evidence-brief)
```

## Rules
- **Decisive, not hedged.** State the bet. "We will build live presence indicators" — not "we could
  consider some form of visibility." If you cannot commit, you are not done deciding.
- **Cite ≥1 internal and ≥1 external fact** where both exist. The claims are the receipts; a decision
  whose claims are all vibes fails the grounding floor for good reason.
- **Confidence is a self-assessment you'll be measured against.** Below the floor without cited
  evidence, the tool refuses — that's the system working. Don't inflate the number; gather evidence.
- **The outcome metric must be falsifiable.** "Improve UX" is not a metric. "Cut time-to-cancel 20% in
  2 weeks" is — it can be checked and the decision revisited against it.
- **The revisit trigger is a promise to look again.** Pin a metric and a window so the revisit sweep
  can reopen it. A decision with no revisit trigger is fire-and-forget.
- **Rejections carry reasons.** "Second provider — improves reliability but not the opaque-progress
  complaint; defer" beats a bare list. The reasons are how a reader trusts the choice.
- **It's immutable.** Once recorded, a change is a *new* record that supersedes this one — never an edit.
  Record it right, or supersede it deliberately.
