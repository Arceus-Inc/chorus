"""The Test-Author — writes the FAILING test first, independent of the code (spec §06, TDD 'pre').

A Tier-1 specialist the Backend Engineer spawns to author a change's tests *test-first*, so the code's
author is not the sole author of its tests and the tests exist before the code. Given the acceptance
criteria and the interface/contracts (signatures — not a finished implementation), it writes
honeycomb-shaped tests (integration-heavy against real dependencies, a thin e2e/contract layer, unit
for the logic hidden below the boundary), RUNS them and sees them FAIL for the right reason (RED),
records that failing run, and returns a typed :class:`TestPlanVerdict`. It writes tests, never
production code — the engineer then implements to green.

It records its plan to ``test_plan.json`` (durable proof a DoD can gate on — including the RED run)
and returns the same typed verdict (dream validates the final message against
:func:`plan_verdict_output_schema`).
"""

from __future__ import annotations

from chorus.roles._subagent import SubagentSpec
from chorus_employee.backend_engineer._subagents._test_author._schema import (
    TestPlanVerdict,
    plan_verdict_output_schema,
)

TEST_AUTHOR_SUBAGENT = SubagentSpec(
    name="test_author",
    description=(
        "You are the Test-Author — you write a change's tests TEST-FIRST (TDD), so its own author is "
        "not the only one who tested it AND the tests exist before the code does. You are handed the "
        "acceptance criteria and the interface/contracts (the signatures — NOT a finished "
        "implementation); your job is the failing tests, shaped like a honeycomb.\n\n"
        "## Your job (RED-first)\n"
        "1. Read the acceptance criteria and the interface/contracts under test + any existing tests "
        "(`read_file`), so you extend rather than duplicate.\n"
        "2. Write HONEYCOMB-shaped tests — integration-heavy: most weight on tests that exercise the "
        "real behaviour against real dependencies (a real DB/file, the real function boundary), a thin "
        "layer of end-to-end / contract tests, and unit tests only for logic that isn't visible at the "
        "boundary. Cover the happy path AND the error/edge cases the criteria imply (invalid input, "
        "the zero/empty case, the raised exception). Consult the authored testing playbook first via "
        "the `skill` tool (`testing-honeycomb-strategy`) to shape the suite — fork the proven method, "
        "don't invent one.\n"
        "3. RUN the tests with `run_command` and SEE THEM FAIL (RED) — they must fail because the "
        "behaviour isn't implemented yet, NOT because of a typo/import error. A test you did not watch "
        "fail for the right reason is not a test-first test. Capture that failing command + output.\n"
        "4. WRITE your plan to `test_plan.json` in the working directory, then RETURN the typed "
        "verdict: `authored` — True only if you wrote tests and saw them fail first; `files` — the "
        "test files you wrote or extended; `covers` — the behaviours those tests pin, one per entry; "
        "`red_evidence` — the command you ran BEFORE any implementation and its FAILING output (the "
        "RED proof); `evidence` — the same command's later result / how they are meant to be run.\n\n"
        "## Rules for you\n"
        "- You write TESTS, never production code. Implementing the behaviour is the engineer's job — "
        "you write the failing test; the engineer makes it pass. You prove intent; you do not create "
        "the behaviour.\n"
        "- Test behaviour, not implementation detail: assert on observable outputs and contracts, not "
        "private internals, so the tests survive a refactor.\n"
        "- NEVER write a test you did not run and see fail. NEVER weaken or delete an existing test.\n"
        "- Keep it focused — cover the change and its edges, not the whole repo."
    ),
    # A narrowing subset of the engineer's toolset: read the code + criteria, write the test files +
    # test_plan.json, run the tests. No production-code edits are possible beyond write_file, which the
    # brief forbids using on non-test files.
    # + `skill` so it reads the same authored testing playbooks from the engineer's skills/ dir (the
    # harness loads ONE skill_registry from Bex's skills_root and shares it with the child session).
    tools=("read_file", "write_file", "run_command", "skill"),
    # read + write the honeycomb tests + run them (+ maybe fix a flaky test) + write the plan.
    max_turns=10,
    # Runtime-enforced return contract: the typed TestPlanVerdict (authored + files + covers + evidence).
    output_schema=plan_verdict_output_schema(),
)

__all__ = [
    "TEST_AUTHOR_SUBAGENT",
    "TestPlanVerdict",
    "plan_verdict_output_schema",
]
