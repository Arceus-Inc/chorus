---
name: test-evidence-discipline
description: How to leave durable, honest proof that the tests ran — redirecting the real runner output into the evidence bundle, writing a substantive summary, and never fabricating or cherry-picking a result.
when_to_use: Read during the run-and-capture step and before declaring done. It is what makes in-beat testing visible to the after-beat verifier, which re-runs your suites against the shipped code.
---

# Test-Evidence Discipline

A test run that happened only in a transcript is invisible to whoever checks the work afterward — and
here the verifier literally re-runs your suites against the code you shipped. So evidence has to be
*durable* (written to disk) and *honest* (the real output, not a hand-typed success). Fabricated or
cherry-picked evidence is the worst failure there is: it's a lie that a re-run instantly exposes.

## The one rule

**Redirect the real runner's output into the evidence bundle, write an honest summary, and never type a
result you didn't get from an actual run.**

## Capture real output

- Run the suite and redirect its full stdout+stderr into the log — e.g. append ` > test_evidence/unit.txt 2>&1`
  for the Node run and ` > test_evidence/e2e.txt 2>&1` for Playwright.
- **Never hand-write the logs.** The verifier re-runs the suites; a log that doesn't match a real run
  (or tests that don't match the app) is caught immediately. Make it real, or it's worse than nothing.
- Capture fresh output every time you re-run after a fix, so the logs reflect the code as shipped.

## Write a substantive summary

`test_evidence/summary.md` is what a teammate reads to trust the work. Include: what you built and how
it's wired; what the unit tests cover; what the e2e flow exercises; the **result** of each suite (how
many passed); the accessibility decisions (semantics, keyboard, focus, contrast); and any tradeoff or
known gap. A stub summary fails the bar — write the real thing.

## Never game the gate

- Don't delete or skip a failing test to go green — a red suite is honest; a green suite that hid a
  failure is a defect you shipped.
- Don't assert trivialities to pad the count. One genuine assertion beats ten hollow ones.
- Before you stop, run the `evidence_scan` tool and clear every finding it reports.

## Before you finish

1. Are `unit.txt` and `e2e.txt` real captured runner output, not hand-written?
2. Does `summary.md` cover what/how/coverage/results/a11y/tradeoffs substantively?
3. Did you re-capture the logs after your last fix?
4. Is every test in the logs one that genuinely passed — nothing skipped or deleted to fake green?
