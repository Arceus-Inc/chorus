---
name: mutation-testing
description: How to prove the TESTS are real, not just green — inject faults into the code (mutants), require the suite to catch (kill) them, and gate on a kill-rate. A suite that never fails when the code is broken proves nothing; mutation testing is the check that the tests would actually fail.
when_to_use: Read when a change carries real logic (a branch, a boundary, a calculation, a parser, a money/permission path) and you want proof the tests guard it — not just that they pass. Use it to turn a green unit bundle into evidence the tests would go RED if the behaviour regressed, and to find the exact assertions that are missing.
---

# Mutation testing — prove the tests would fail if the code were wrong

A green test suite proves the tests **pass against the code as written**. It does not prove the tests
would **fail if the code were wrong** — and those are different claims. A test that calls the function
but asserts almost nothing (`assert result is not None`), or that pins the implementation instead of
the behaviour, passes forever, including when the behaviour breaks. Coverage counts *lines executed*,
not *behaviour asserted* — 100% coverage with vacuous assertions is 0% protection. Mutation testing is
the check coverage can't give you: it deliberately breaks the code and demands the tests notice.

## 1. The mechanic: inject faults, require the suite to catch them

A mutation tool makes many tiny, single-point edits to your code — a **mutant** each: `a + b` → `a - b`,
`>` → `>=`, `return x` → `return None`, `if cond` → `if not cond`, a constant `1` → `0`. For each
mutant it runs your test suite:

- **Killed** — at least one test failed. Good: a test actually guards that line.
- **Survived** — every test still passed with the code broken. That is a **hole**: the behaviour on
  that line is unasserted. A survivor is a bug your suite would ship.

The **kill rate** = killed / (killed + survived). It is the fraction of injected faults your tests
caught — a direct, adversarial measure of test strength that coverage cannot fake.

## 2. Bind to the stack's mutation tool — this is the pattern, not one tool

Stack-agnostic; use what the ecosystem ships:

- **Python** — `mutmut` (lightest) or `cosmic-ray`.
- **JS / TS** — Stryker (`@stryker-mutator`).
- **Java** — PIT (`pitest`).
- **Go** — `go-mutesting` / `gremlins`.
- **Rust** — `cargo-mutants`.

Install it in the sandbox (it is UNRESTRICTED — `pip install mutmut`, `npm i -D @stryker-mutator/core`,
…) and point it at **the module you changed**, not the whole repo — mutation testing is O(mutants ×
test-time), so scope it to the diff's logic or a slow run will eat the beat.

## 3. Run it, then gate on a kill-rate threshold

The tool's own exit code is often a bitmask, not a clean pass/fail. Make the gate explicit: run the
tool, read the survivor count, and exit non-zero below your threshold, so `test_evidence` records a
real red/green. A concrete Python recipe with `mutmut`:

```bash
# scope to the changed module; mutmut auto-detects pytest as the runner
mutmut run --paths-to-mutate slugify.py || true   # its own exit code is a bitmask — don't trust it
# threshold in one line: fail the gate if ANY mutant survived (100% kill for a small pure module),
# or compute a ratio for a larger surface:
python -c "import sys,subprocess as s; o=s.run(['mutmut','results'],capture_output=True,text=True).stdout; \
survived=o.count('survived'); sys.exit(1 if survived else 0)"
```

For a small, pure module aim for **100% kill** (every mutant killed) — anything less names a specific
missing assertion. For a larger or partly-glue module, pick a threshold (e.g. **≥ 80%**) and record it;
don't let it drift down silently.

## 4. A survivor is a to-do list, not a nuisance — strengthen the TEST, never weaken the tool

Each surviving mutant tells you exactly which behaviour is unguarded. The fix is a **new or stronger
assertion** that kills it:

- `>` → `>=` survived ⇒ you never test the boundary value. Add the `== boundary` case.
- `return x` → `return None` survived ⇒ you never assert the return value. Assert it.
- a constant mutation survived ⇒ that constant's effect is unobserved. Assert the output that depends
  on it.

**Never** kill a survivor by excluding the file, lowering the threshold to 0, or deleting the mutant —
that games the gate into meaninglessness, the same sin as swapping a no-op for a linter. And **never**
weaken a real test to speed the run. The point is a suite that goes RED when the behaviour regresses.

## 5. Record it as its own `test_evidence` gate

Hand the mutation run to `test_evidence` as a named gate alongside lint/types/unit:

```
test_evidence(gates=[
  {"name": "unit",     "command": "pytest -q"},
  {"name": "mutation", "command": "bash run_mutation_gate.sh"},   # the run + threshold check above
])
```

A green `test_evidence/manifest.json` with a `mutation` gate that actually ran and passed is proof the
tests are *load-bearing*, not decorative — the deepest answer to "a suite that passes on mocks proves
the mocks."

## Why this is a skill, not a tool

Which mutation tool, which module to scope, what kill-rate is honest for this change is per-stack,
per-diff know-how — discovered, not hardcoded (§03). `test_evidence` stays a stack-blind executor; this
skill is how you decide what mutation gate to hand it.
