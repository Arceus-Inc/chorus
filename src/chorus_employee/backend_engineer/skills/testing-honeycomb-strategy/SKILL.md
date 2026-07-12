---
name: testing-honeycomb-strategy
description: How to write a change's tests TEST-FIRST and shape them like a honeycomb — integration-heavy against real dependencies, a thin e2e/contract cap, unit only for what hides below the boundary. The method the Test-Author forks instead of inventing one.
when_to_use: Read before authoring tests for a change (the Test-Author's first move). Use it to write the FAILING test first, decide what to test at which layer, and pick assertions that survive a refactor. A test you did not watch fail proves nothing.
---

# Testing, honeycomb-shaped — write it failing first, weight it in the middle

Two ideas do the work: **test-first** (write the test before the code, watch it fail for the right
reason), and **the honeycomb** (put most of your weight on integration tests against real
dependencies, not a broad base of mock-heavy unit tests). A green suite that never failed first, or
that only ever exercised mocks, proves almost nothing.

## 1. RED first — the test exists before the behaviour

You are handed the acceptance criteria and the interface/contracts — the signatures, not a finished
implementation. Write the test against that contract, then RUN it and SEE IT FAIL:

- It must fail because the behaviour **isn't implemented yet** — an `AssertionError`, a `501`, a
  `NotImplementedError`, a missing row — **not** because of a typo, a bad import, or a fixture error.
  A red bar for the wrong reason is a broken test, not a test-first test.
- Capture that failing command and its output verbatim — it is your `red_evidence`. It is the proof
  the test could ever fail, which is the only thing that makes a later green bar meaningful.
- You write the test; the engineer makes it pass. Never edit production code to turn your own bar
  green — if the test reveals a real bug, report the gap.

If you cannot make the test fail first, you do not yet understand the contract well enough to test it.

## 2. Shape the suite like a honeycomb, not a pyramid

Weight tests by how much confidence they buy per unit of maintenance:

- **Thin e2e / contract cap (few):** one or two tests that drive the real entry point — boot the
  service, issue a real request, assert the real response/status. Proves it is wired together.
- **Integration heart (most of your weight):** exercise the real behaviour across the real boundary
  with real collaborators — a real SQLite file/temp DB, the real function, the real HTTP handler.
  This is where bugs actually live (serialization, transactions, auth, error mapping), so this is
  where the tests live. Prefer a real dependency over a mock; reach for a fake only at a truly
  external edge (a paid API, the clock, the network).
- **Unit base (few, targeted):** only for logic that isn't observable at the boundary — a tricky
  parser, a pricing calculation, a state machine. If a unit test would just restate the code, skip it.

Mock-heavy unit tests that stub the very thing under test prove the mocks, not the system. When in
doubt, push a test **down** the honeycomb toward a more real dependency, not up toward more mocks.

## 3. Cover the edges the criteria imply, not just the happy path

For each behaviour, the criteria usually imply more than the sunny case. Write the failing test for:

- the **happy path** (the stated contract),
- the **error path** (invalid input → the specified 4xx/exception, not a 500),
- the **boundary/empty/zero** case (empty list, missing field, first/last, duplicate),
- the **idempotency / persistence** case when the contract claims it (same key twice → one effect;
  survives a restart).

## 4. Assert on behaviour, so the tests survive a refactor

Assert on **observable outputs and contracts** — the returned value, the response body/status, the
row that landed — never on private internals or call-order of mocks. A test that breaks when you
rename a private helper is testing the implementation, not the behaviour. Name each test for the
behaviour it pins (`test_pay_twice_with_same_key_charges_once`), so a failure reads as a spec
violation, not a puzzle.

## 5. Run them, record the plan

A test you did not run is not a test. Run the suite, keep the `red_evidence` (the first failing run)
and the command to re-run it, and write `test_plan.json` — the durable proof the DoD gates on: the
files you wrote, the behaviours they now pin, and that they were seen RED before the code existed.
