---
name: unit-testing-with-node-test
description: How to write fast, zero-dependency unit tests with Node's built-in runner — importing your pure ES modules directly, asserting real behavior, and covering the branches that matter (including error paths).
when_to_use: Read when unit-testing with Node's built-in runner — the zero-dependency, no-framework path. If you scaffolded a framework, you'll likely use its runner instead (see `component-testing` for Vitest + Testing Library); the branch-coverage and anti-hollow discipline below is identical for any runner.
---

# Unit Testing with node:test

Node ships a test runner and assertion library — `node --test` with `node:test` and `node:assert` — so
unit tests need zero dependencies and run in milliseconds. This is the **no-framework path**; a framework
stack uses its own runner (`vitest run`, `jest`) wired to `npm test` instead — but the goal is the same:
prove your logic is correct across its real branches, not inflate a pass count with tests that assert
nothing. Whichever runner you use, wire it to `npm test` so the evidence and the re-run line up.

## The one rule

**Test real behavior through the module's public surface, covering the branches that matter — and every
test would actually fail if the logic were wrong.**

## The shape

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { totalWithTax } from '../src/pricing.js';

test('applies tax to the subtotal', () => {
  assert.equal(totalWithTax(100, 0.1), 110);
});
```

- Put specs under `tests/` as `*.test.js`. Run them with `node --test`.
- Import the real module — never re-implement the logic in the test, and never test a mock instead of
  the code.

## Cover what matters

- Test each meaningful branch: the happy case, the boundaries (0, empty, max), and the **error paths**
  (invalid input throws or returns the error result). An untested error branch is where bugs hide.
- One behavior per test, named as a sentence about that behavior. When it fails, the name should tell
  you what broke.
- Use `assert.throws` for expected failures, `assert.deepEqual` for structures.

## Avoid hollow tests

- A test that asserts `true === true`, re-computes the expected value with the same code under test, or
  never calls the real function proves nothing. A reviewer will (rightly) call it a blocker.
- Prefer a few genuine assertions over many empty ones. Coverage of *branches* beats coverage of
  *lines*.

## Before you finish

1. Does each test import and exercise the real module (not a mock, not a re-implementation)?
2. Are the error/boundary branches covered, not just the happy path?
3. Would every test genuinely fail if you broke the logic it names?
4. Did you run `node --test` and see real green output (not a hand-written log)?
