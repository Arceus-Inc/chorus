---
name: debugging-failing-tests
description: How to turn a red run green the right way — reading the actual failure and Playwright trace, forming a hypothesis, fixing the root cause (code or test), and re-running, without ever deleting a failing test to go green.
when_to_use: Read whenever a unit or e2e run fails. It is the disciplined loop that gets to green honestly; test-evidence-discipline covers capturing the fresh output afterward.
---

# Debugging Failing Tests

A failing test is information, not an obstacle. The wrong response — deleting it, skipping it, or
loosening the assertion until it passes — ships the bug and hides it. The right response is to read what
the failure is actually telling you, fix the cause, and re-run.

## The one rule

**Read the real error, fix the root cause (which may be the code *or* a wrong test), and re-run — never
weaken or remove a test just to see green.**

## Read the failure precisely

- Read the actual assertion message: expected vs received. The diff usually names the bug. Don't guess
  from the test name.
- For Playwright, use the trace: run with `--trace on` (or `--debug`), open the trace to see the DOM,
  the failing locator, and the step where it went wrong. A "locator not found" often means a wrong
  role/label — or that the feature genuinely didn't render.
- Reproduce narrowly: run the single failing test (`node --test tests/x.test.js`, or Playwright's `-g`)
  to iterate fast.

## Decide: is the code wrong or the test wrong?

- If the app doesn't do what the intent asked, fix the **code**. This is the common case.
- If the test asserts the wrong thing, fix the **test** — but be honest: a test is only "wrong" if it
  misstates the intended behavior, not because it's inconvenient. Weakening a correct assertion to pass
  is faking green.

## Close the loop

- Make one change, re-run, confirm. Don't shotgun several changes at once — you won't know what fixed it.
- Once green, re-capture the evidence logs so they reflect the fixed code.

## Before you finish

1. Did you read the actual expected-vs-received message (and the Playwright trace for e2e)?
2. Did you fix the root cause rather than loosen the assertion?
3. If you changed a test, is it because the behavior it asserted was genuinely wrong?
4. Did every suite go green on a real re-run, with fresh captured logs?
