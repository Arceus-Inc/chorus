"""Per-role run-lease TTL — a research-heavy role widens its lease past the org default (spec 06 §2).

The scheduler leases each beat for the assignee role's ``lease_ttl_s`` when set, else its own default —
so a beat that blocks for minutes inside one uninterrupted ``web_research`` sweep isn't reaped by the
stale-run watchdog.
"""

from __future__ import annotations

import pytest

from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import Ledger
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


class _FakeBeat:
    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="")


class _FakeWorkforce:
    def get(self, employee_id: str) -> Employee:
        raise KeyError(employee_id)


def _scheduler(ledger: Ledger) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(),
        beat_runner=_FakeBeat(),
        roles=RoleRegistry.from_plugins(default_roles()),
        lease_ttl_s=300.0,
        max_concurrent_runs=1,
    )


def test_marketer_lease_uses_its_role_override(ledger: Ledger) -> None:
    sched = _scheduler(ledger)
    ttl = sched._lease_seconds_for(Employee(id="mira", name="Mira", role="marketer"))
    assert ttl == 1200.0  # the marketer's widened, depth-2-research lease (marketer/_harness.py)


def test_role_without_override_falls_back_to_default(ledger: Ledger) -> None:
    sched = _scheduler(ledger)
    ttl = sched._lease_seconds_for(Employee(id="ada", name="Ada", role="engineer"))
    assert ttl == 300.0  # the scheduler default


def test_unknown_role_falls_back_to_default(ledger: Ledger) -> None:
    sched = _scheduler(ledger)
    ttl = sched._lease_seconds_for(Employee(id="x", name="X", role="nonexistent"))
    assert ttl == 300.0
