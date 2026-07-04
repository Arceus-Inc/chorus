"""The Frontend Engineer's Definition of Done — intent -> typed :class:`~chorus.outcomes.Verifier`.

The Frontend Engineer's failure mode is *shipping code that looks done but doesn't run or isn't tested*,
so — like the Designer and Marketer — its DoD **leads with a deterministic floor**, not a self-report.
The floor is the **evidence contract**: a working app entry, real unit + e2e test suites in their own
dirs, and a durable ``test_evidence/`` bundle that captured the actual test runs. Claiming "the tests
passed" in the transcript is invisible to the after-beat oracle; writing the captured runner output and a
substantive summary to disk is not — that is what makes "it was tested" checkable at all.

The floor is authored with :func:`chorus.outcomes.python_check`, which compiles to a single, quoting-safe
``python -c`` command that verifies **identically on every OS** — POSIX ``test``/``grep`` floors could
not run under the ``cmd.exe`` the dream oracle uses on Windows, which is the concrete "DoD fails on the
Windows env" failure this replaces. Globs are scoped to the app's own dirs so a ``node_modules/`` an
``npm install`` may create never inflates the counts.

The floor is *necessary, not sufficient*: whether the UI genuinely works and the diff is sound is pressed
inside the beat by the UI-Tester and Code-Reviewer subagents, and the suites are RE-RUN against the
shipped code after the beat. The artifact class is ``pr`` — the Frontend Engineer lands running code, so
it shares the Engineer's ``pr`` outcome lander.
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
    APP_ENTRY,
    E2E_TEST_LOG,
    E2E_TESTS_DIR,
    TEST_EVIDENCE_SUMMARY,
    UNIT_TEST_LOG,
    UNIT_TESTS_DIR,
)

# A test-runner leaves recognisable output; requiring the captured logs to look like real runner output
# (very leniently — any of these words) rejects an empty or hand-waved file without being brittle about
# the exact runner format. The authoritative anti-fabrication check is the after-beat re-run.
_UNIT_RUN_MARKERS = (r"\btests?\b", r"\bpass", r"\bfail", r"\bok\b", r"assert", r"# tests")
_E2E_RUN_MARKERS = (r"passed", r"failed", r"\bpass", r"\bfail", r"playwright", r"\brunning\b", r"\bspec")


def _dod_checks() -> list[dict[str, object]]:
    """The evidence-contract floor: a working app entry, unit + e2e suites, and a real evidence bundle."""
    return [
        # (1) a working app entry actually shipped.
        file_exists(APP_ENTRY),
        # (2) unit tests exist, in their own dir (scoped glob — never counts node_modules).
        glob_at_least(f"{UNIT_TESTS_DIR}/**/*.test.*", 1),
        # (3) e2e tests exist, in their own dir.
        glob_at_least(f"{E2E_TESTS_DIR}/**/*.spec.*", 1),
        # (4) the unit run was captured and looks like real runner output.
        file_exists(UNIT_TEST_LOG),
        file_matches_any(UNIT_TEST_LOG, list(_UNIT_RUN_MARKERS), label="captured unit-test run output"),
        # (5) the e2e run was captured and looks like real Playwright output.
        file_exists(E2E_TEST_LOG),
        file_matches_any(E2E_TEST_LOG, list(_E2E_RUN_MARKERS), label="captured e2e-test run output"),
        # (6) a substantive human-readable summary of what was built, tested, and the result.
        file_exists(TEST_EVIDENCE_SUMMARY),
        min_words(TEST_EVIDENCE_SUMMARY, 120),
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
