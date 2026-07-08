"""The Backend Engineer's standing routines (spec §14) — what makes it an engineer, not a
code-generator-on-demand. Deterministic (no LLM): the plugin declares both non-deferred routines from
the spec's table, each report/propose-only and coalesced.
"""

from __future__ import annotations

import pytest

from chorus.ledger import RoutineConcurrency
from chorus_employee.backend_engineer import (
    BACKEND_ENGINEER_ROUTINES,
    backend_engineer_plugin,
)

pytestmark = pytest.mark.unit


def test_plugin_declares_the_standing_routines() -> None:
    plugin = backend_engineer_plugin()
    assert plugin.declared_routines == BACKEND_ENGINEER_ROUTINES
    keys = {r.routine_key for r in BACKEND_ENGINEER_ROUTINES}
    assert keys == {"backend-engineer-dependency-scan", "backend-engineer-slo-watch"}
    assert all(r.concurrency is RoutineConcurrency.COALESCE for r in BACKEND_ENGINEER_ROUTINES)


def test_dependency_scan_is_weekly_and_propose_only() -> None:
    scan = next(
        r for r in BACKEND_ENGINEER_ROUTINES if r.routine_key == "backend-engineer-dependency-scan"
    )
    assert scan.schedule == "0 9 * * 1"  # weekly, Monday 09:00
    assert "lockfile" in scan.intent_template
    assert "do not merge" in scan.intent_template.lower()


def test_slo_watch_is_daily_and_report_only() -> None:
    watch = next(
        r for r in BACKEND_ENGINEER_ROUTINES if r.routine_key == "backend-engineer-slo-watch"
    )
    assert watch.schedule == "0 9 * * *"  # daily 09:00
    assert "SLO" in watch.intent_template
    assert "report only" in watch.intent_template.lower()


def test_flaky_quarantine_is_not_declared_yet() -> None:
    # §14 marks flaky-test quarantine `deferred` — it needs an evidence *history* the single-bundle
    # test_evidence primitive doesn't carry yet. Only the two non-deferred routines are declared.
    keys = {r.routine_key for r in BACKEND_ENGINEER_ROUTINES}
    assert not any("flaky" in key for key in keys)
