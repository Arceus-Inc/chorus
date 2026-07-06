"""The Frontend Engineer's Definition of Done — intent -> typed :class:`~chorus.outcomes.Verifier`.

The Frontend Engineer's failure mode is *shipping code that looks done but doesn't run or isn't tested*,
so — like the Designer and Marketer — its DoD **leads with a deterministic floor**, not a self-report.
The floor is the **evidence contract**, and it is deliberately **framework-agnostic**: it asserts a real,
runnable project (a ``package.json`` with a wired ``test`` script), a real end-to-end harness (a
Playwright config — the one stack-independent browser check), and a durable ``test_evidence/`` bundle
that captured the actual unit + e2e runs and records the stack decision. It names no entry file, no
language, and no framework — a vanilla, React, Vue, or Svelte project passes it identically. Claiming
"the tests passed" in the transcript is invisible to the after-beat oracle; writing the captured runner
output and a substantive summary to disk is not — that is what makes "it was tested" checkable at all.

The floor is authored with :func:`chorus.outcomes.python_check`, which compiles to a single, quoting-safe
``python -c`` command that verifies **identically on every OS** — POSIX ``test``/``grep`` floors could
not run under the ``cmd.exe`` the dream oracle uses on Windows, which is the concrete "DoD fails on the
Windows env" failure this replaces. The markers checked are top-level (``package.json``,
``playwright.config.*``) so a ``node_modules/`` an ``npm install`` creates never confuses the floor.

The floor is *necessary, not sufficient*: whether the UI genuinely works and the diff is sound is pressed
inside the beat by the UI-Tester and Code-Reviewer subagents, and the suites are RE-RUN (``npm test`` +
``npx playwright test``) against the shipped code after the beat. The artifact class is ``pr`` — the
Frontend Engineer lands running code, so it shares the Engineer's ``pr`` outcome lander.
"""

from __future__ import annotations

from chorus.outcomes import (
    Verifier,
    file_exists,
    file_matches,
    file_matches_any,
    glob_at_least,
    min_words,
    python_check,
)
from chorus_employee.frontend_engineer._brief import (
    E2E_TEST_LOG,
    TEST_EVIDENCE_SUMMARY,
    UNIT_TEST_LOG,
)

# A test-runner leaves recognisable output; requiring the captured logs to look like real runner output
# (very leniently — any of these words) rejects an empty or hand-waved file without being brittle about
# WHICH runner ran (node:test, vitest, jest, ...). The authoritative anti-fabrication check is the
# after-beat re-run of `npm test` / `npx playwright test`.
_UNIT_RUN_MARKERS = (
    r"\btests?\b",
    r"\bpass",
    r"\bfail",
    r"\bok\b",
    r"assert",
    r"# tests",
    r"\bsuites?\b",
)
_E2E_RUN_MARKERS = (
    r"passed",
    r"failed",
    r"\bpass",
    r"\bfail",
    r"playwright",
    r"\brunning\b",
    r"\bspec",
)
# Neutral decision words — the summary must record WHICH stack was chosen and why. No framework NAMES
# here on purpose: the floor must never bias the engineer toward any particular stack.
_STACK_DECISION_MARKERS = (
    r"\bstack\b",
    r"\bframework\b",
    r"\bchose\b",
    r"\bchosen\b",
    r"\brationale\b",
    r"trade",
)


def _dod_checks() -> list[dict[str, object]]:
    """The framework-agnostic evidence floor: a real project, an e2e harness, and a real evidence bundle."""
    return [
        # (1) a real, runnable frontend project — the universal marker of production-real frontend work,
        #     whatever the stack (even a Vite-vanilla app has one).
        file_exists("package.json"),
        # (2) a unit-test entry is WIRED as the project's `test` script (any runner: node:test/vitest/jest).
        file_matches("package.json", r'"test"\s*:', label="a wired `test` script in package.json"),
        # (3) an end-to-end harness is configured — Playwright is the one stack-independent browser check;
        #     the config is top-level so this never counts a node_modules/ copy.
        glob_at_least("playwright.config.*", 1),
        # (4) the unit run was captured and looks like real runner output.
        file_exists(UNIT_TEST_LOG),
        file_matches_any(
            UNIT_TEST_LOG, list(_UNIT_RUN_MARKERS), label="captured unit-test run output"
        ),
        # (5) the e2e run was captured and looks like real Playwright output.
        file_exists(E2E_TEST_LOG),
        file_matches_any(
            E2E_TEST_LOG, list(_E2E_RUN_MARKERS), label="captured e2e-test run output"
        ),
        # (6) a substantive human-readable summary that records the stack decision and the test result.
        file_exists(TEST_EVIDENCE_SUMMARY),
        min_words(TEST_EVIDENCE_SUMMARY, 150),
        file_matches_any(
            TEST_EVIDENCE_SUMMARY,
            list(_STACK_DECISION_MARKERS),
            label="the stack decision + rationale",
        ),
        file_matches(
            TEST_EVIDENCE_SUMMARY,
            r"pass|passed|fail|failed|test|e2e|unit",
            label="a test-result summary",
        ),
    ]


def frontend_engineer_dod(intent: str) -> Verifier:
    """The Frontend Engineer's DoD generator: a cross-platform Command floor over the evidence bundle."""
    del intent  # the deliverable floor is the same regardless of the specific surface asked for
    # 900s: the floor is a fast file scan, but it is generous for a large worktree; the *build/test*
    # runs happen inside the beat, not here.
    return Verifier.command(python_check(_dod_checks()), artifact_class="pr", timeout_s=900)


__all__ = ["frontend_engineer_dod"]
