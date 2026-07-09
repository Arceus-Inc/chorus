"""The Backend Engineer's standing routines (spec §14).

What makes it an engineer, not a code-generator-on-demand: two report/propose-only routines that fire
a fresh, DoD-gated beat on their own cadence. Neither merges or touches production on its own — a
proposed upgrade or a filed breach still stages for approval like any other beat. ``BACKEND_ENGINEER_ROUTINES``
is what :func:`chorus_employee.backend_engineer.backend_engineer_plugin` hands to
``RolePlugin.declared_routines``. The third routine the spec lists, flaky-test quarantine, is marked
``deferred`` in spec §14 — it needs an evidence *history* to detect non-determinism from, which the
single-bundle ``test_evidence`` primitive doesn't carry yet.
"""

from __future__ import annotations

from chorus.ledger import RoutineConcurrency
from chorus.roles._routine_declaration import RoutineDeclaration

# Weekly dependency & vuln scan, filed every Monday 09:00. The you-build-it-you-run-it hygiene loop:
# scans the lockfile + SCA for vulnerable/outdated deps and proposes a bounded upgrade PR with the
# gates re-run — report/propose only, it never trips a merge on its own.
BACKEND_ENGINEER_DEPENDENCY_SCAN = RoutineDeclaration(
    routine_key="backend-engineer-dependency-scan",
    intent_template=(
        "Dependency & vuln scan: read the repo's lockfile(s) and run its ecosystem's SCA tool "
        "(e.g. `pip-audit`, `npm audit`, `govulncheck`, `cargo audit`) to find vulnerable or outdated "
        "dependencies. For each finding, propose a bounded upgrade — smallest version bump that clears "
        "it — and re-run the discovered test/build gates (`test_evidence`) so the proposal ships with "
        "proof it still builds green. Report and propose only; do not merge or land without review."
    ),
    schedule="0 9 * * 1",  # == Schedule.weekly(Weekday.MONDAY, at="09:00")
    concurrency=RoutineConcurrency.COALESCE,
)

# Daily SLO / error-budget watch, filed 09:00. Checks the shipped services' latency percentiles + error
# rate against their SLOs; files a breach or a burning error budget as a fresh problem (with the trace)
# for a remediation beat — it never remediates in the routine itself.
BACKEND_ENGINEER_SLO_WATCH = RoutineDeclaration(
    routine_key="backend-engineer-slo-watch",
    intent_template=(
        "SLO / error-budget watch: check the latency percentiles (p95/p99, never averages) and error "
        "rate of the services this project ships against their declared SLOs — read them from the "
        "repo's own monitoring config, dashboards, or `docs/` if declared; if none are declared, note "
        "that as the finding instead of inventing a number. On a breach or a burning error budget, "
        "file it as a fresh problem with the trace/evidence attached for a remediation beat. Report "
        "only; do not attempt the fix in this routine."
    ),
    schedule="0 9 * * *",  # == Schedule.daily(at="09:00")
    concurrency=RoutineConcurrency.COALESCE,
)

BACKEND_ENGINEER_ROUTINES: tuple[RoutineDeclaration, ...] = (
    BACKEND_ENGINEER_DEPENDENCY_SCAN,
    BACKEND_ENGINEER_SLO_WATCH,
)

__all__ = [
    "BACKEND_ENGINEER_DEPENDENCY_SCAN",
    "BACKEND_ENGINEER_ROUTINES",
    "BACKEND_ENGINEER_SLO_WATCH",
]
