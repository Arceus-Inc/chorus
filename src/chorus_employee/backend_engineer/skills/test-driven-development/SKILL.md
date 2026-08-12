---
name: test-driven-development
description: "TDD for Bex: RED-GREEN-REFACTOR with tools. Failing Intent-pinned tests before production code. Prefer this over spawning test_author."
when_to_use: Load before any behavior change (new feature, bug fix, API/migration work). Use instead of inventing a test-after workflow. Spawn test_author only when you must not author the proof yourself.
---

# Test-Driven Development (tools first)

**Iron law:** no production code without a failing test first.

If you already wrote production code, delete it and start from the failing test. Do not keep it as “reference.”

**Ladder:** tools run the cycle; this skill is the procedure; spawn `test_author` only when isolation earns it (`tool > skill > spawn`).

## Cycle (vertical slices)

One behavior at a time — not a pile of tests then a pile of code:

1. **RED** — Write one test that pins the **ticket Intent signature exactly** (ctors, return types, route semantics). Run it (`test_red` or `python -m pytest … -q`). Confirm it fails for the missing behavior (not a typo/import/fixture error). Keep that output as red proof.
2. **GREEN** — Minimal production code to pass that test. Nothing else.
3. **REFACTOR** — Clean up with tests still green. No new behavior.
4. Repeat for the next Intent bullet.

## Intent fidelity (quality bar)

Agent-green suites that skip the contract are FAIL:

- Pin every public API from TASK Intent verbatim: constructor arguments, return values, and operation-specific semantics.
- When an operation accepts an identifier, prove it selects that exact resource while another eligible resource exists.
- Do not invent a thinner API to make tests easy.
- Prefer real collaborators (temp SQLite, real HTTP) over mocks. For suite shape, load `testing-honeycomb-strategy`.
- Avoid stdlib module-name collisions when naming new files. An explicit task filename wins; keep its imports unambiguous and prove test collection from a clean environment.

## Tools

- `write_file` / `apply_patch` — tests first, then production
- `test_red` / `run_command` — watch RED, then GREEN
- `test_evidence` — record gates after the suite is honest
- `skill(testing-honeycomb-strategy)` — integration-heavy honeycomb shape

## When NOT to spawn `test_author`

Default: **you** load this skill and write the failing tests yourself.

Spawn only when isolation helps (independent forged `test_plan.json`, or a suite you must not author alone). Never spawn to wrap a single `pytest` call.
