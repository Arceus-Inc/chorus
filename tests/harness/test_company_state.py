"""The company-state packet (free-run checklist #5).

An executive beat's subject IS the company: goal tree, workforce, open work, spend. That truth
lives in the ledger, not the worktree — so a review beat was structurally unable to cite it and
its evaluator rightly failed it ("goal tree/health, work logs, and spend artifacts are
missing", live 2026-07-18). The factory now mirrors ``company_state.json`` into the worktree
for any role holding ``governance_read`` (the executive signature — role-agnostic, nothing
hardcoded to the CEO): ledger facts become citable files.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from chorus.ledger import Goal, Task
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration


def _factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Any
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
        ledger=ledger,
    )
    return factory, captured


def test_governance_role_gets_the_company_state_packet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id="cass", name="Cass", role="ceo"))
        ledger.employees.create(Employee(id="rex", name="Rex", role="backend_engineer"))
        root = ledger.goals.create(Goal(id=str(uuid.uuid4()), title="Reach $1M MRR"))
        child = ledger.goals.create(
            Goal(id=str(uuid.uuid4()), title="+100 signups", parent_id=root.id)
        )
        ledger.tasks.submit(
            Task(
                id=str(uuid.uuid4()),
                intent="Ship the landing page",
                assignee_employee_id="rex",
                goal_id=child.id,
            )
        )
        factory, _ = _factory(monkeypatch, tmp_path, ledger)
        mat = factory.materialize(Employee(id="cass", name="Cass", role="ceo"))

        packet = json.loads((mat.working_dir / "company_state.json").read_text("utf-8"))
        assert {g["title"] for g in packet["goals"]} == {"Reach $1M MRR", "+100 signups"}
        assert any(g["parent_id"] == root.id for g in packet["goals"])
        roster = {e["id"]: e for e in packet["workforce"]}
        assert roster["rex"]["role"] == "backend_engineer"
        assert "spent_monthly_cents" in roster["rex"]
        assert [t["assignee"] for t in packet["open_tasks"]] == ["rex"]
        assert packet["open_tasks"][0]["goal_id"] == child.id
    finally:
        ledger.close()


def test_non_governance_role_gets_no_packet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id="rex", name="Rex", role="backend_engineer"))
        factory, _ = _factory(monkeypatch, tmp_path, ledger)
        mat = factory.materialize(Employee(id="rex", name="Rex", role="backend_engineer"))
        assert not (mat.working_dir / "company_state.json").exists()
    finally:
        ledger.close()
