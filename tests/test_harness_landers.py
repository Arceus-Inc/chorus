"""The harness factory autowires its employees' landers (spec 14 F7).

The factory owns *execution* — dream, creds, the per-employee worktrees. Landing an employee's
deliverable (the engineer's PR, the manager's subtree, the reviewer's verdict) is part of that
execution, so the factory exposes the :class:`LanderRegistry` the kernel lands passed beats through.
The consumer wires it once, symmetric with the runner seam:
``Chorus.build(..., beat_runner_for=factory.runner_for, landers=factory.landers)`` — no hand-built
``default_landers`` at every call site.
"""

from __future__ import annotations

import pytest

from chorus.ledger import SqliteLedger
from chorus.outcomes import LanderRegistry
from chorus.roles import RoleRegistry, default_roles
from chorus_harness import EmployeeHarnessFactory

pytestmark = pytest.mark.integration


def _factory(**over: object) -> EmployeeHarnessFactory:
    base: dict[str, object] = {
        "api_key": "k",
        "base_url": "u",
        "deployment": "d",
        "company_id": "acme",
        "roles": RoleRegistry.from_plugins(default_roles()),
    }
    base.update(over)
    return EmployeeHarnessFactory(**base)  # type: ignore[arg-type]


def test_landers_is_a_registry_with_the_engineer_pr_lander() -> None:
    landers = _factory().landers
    assert isinstance(landers, LanderRegistry)
    assert "pr" in landers  # the Engineer's deliverable lands without needing a ledger


def test_landers_adds_manager_and_reviewer_when_a_ledger_is_present() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        landers = _factory(ledger=ledger).landers
        assert "pr" in landers  # engineer
        assert "subtree" in landers  # manager (reads its delegated children from the ledger)
        assert "verdict" in landers  # reviewer (reads the recorded verdict)
    finally:
        ledger.close()
