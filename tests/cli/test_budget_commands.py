"""The console's budget verbs — set/list/raise/dismiss over the real budget repos (spec 04 §3)."""

from __future__ import annotations

import io
from datetime import datetime

import pytest

from chorus.ledger import BudgetPolicy, BudgetScope, CostEvent, Ledger
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


def _session(ledger: Ledger) -> CliSession:
    return CliSession(ledger=ledger, clock=lambda: _NOW, company_id="acme")


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(
        line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY
    )
    return signal, buffer.getvalue()


def _spend(ledger: Ledger, employee_id: str, cents: int) -> None:
    ledger.cost_events.record(
        CostEvent(
            id=uid(f"ce_{cents}"),
            employee_id=employee_id,
            provider="dream",
            model="m",
            cost_cents=cents,
            occurred_at=_NOW,
        )
    )


# -- set --------------------------------------------------------------------------------------------


def test_set_employee_budget_creates_a_policy(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    _, out = _run("budget set employee alice 500", _session(ledger))
    assert out.startswith("set ") and "employee alice cap 500 cents" in out
    policies = ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, "alice")
    assert len(policies) == 1 and policies[0].amount == 500


def test_set_company_budget_uses_the_session_company(ledger: Ledger) -> None:
    _run("budget set company 10000", _session(ledger))
    policies = ledger.budget_policies.by_scope(BudgetScope.COMPANY, "acme")
    assert len(policies) == 1 and policies[0].amount == 10000


def test_set_is_an_upsert(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    _run("budget set employee alice 500", _session(ledger))
    _, out = _run("budget set employee alice 800", _session(ledger))
    assert "updated" in out
    policies = ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, "alice")
    assert len(policies) == 1 and policies[0].amount == 800  # not a second row


def test_set_with_flags(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    _run("budget set employee alice 500 --warn=50 --window=weekly", _session(ledger))
    policy = ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, "alice")[0]
    assert policy.warn_percent == 50 and policy.window_kind == "weekly"


def test_set_bad_scope_errors(ledger: Ledger) -> None:
    _, out = _run("budget set department x 500", _session(ledger))
    assert "error:" in out and "department" in out


def test_set_bad_amount_errors(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    _, out = _run("budget set employee alice lots", _session(ledger))
    assert "error:" in out


def test_set_wrong_arity_reports_usage(ledger: Ledger) -> None:
    _, out = _run("budget set employee alice", _session(ledger))  # missing amount
    assert "usage: budget set" in out


def test_set_company_wrong_arity_reports_usage(ledger: Ledger) -> None:
    _, out = _run("budget set company", _session(ledger))  # missing amount
    assert "usage: budget set" in out


def test_set_zero_amount_errors(ledger: Ledger) -> None:
    _, out = _run("budget set company 0", _session(ledger))
    assert "error:" in out and "positive" in out


def test_set_bad_window_errors(ledger: Ledger) -> None:
    _, out = _run("budget set company 500 --window=daily", _session(ledger))
    assert "error:" in out and "daily" in out


def test_set_bad_warn_errors(ledger: Ledger) -> None:
    _, out = _run("budget set company 500 --warn=high", _session(ledger))
    assert "error:" in out


def test_set_with_no_args_reports_usage(ledger: Ledger) -> None:
    _, out = _run("budget set", _session(ledger))
    assert "usage: budget set" in out


# -- list (dashboard) -------------------------------------------------------------------------------


def test_list_empty(ledger: Ledger) -> None:
    _, out = _run("budget", _session(ledger))
    assert "no budgets" in out


def test_list_shows_spend_and_status(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bp1"), scope_type=BudgetScope.EMPLOYEE, scope_id="alice", amount=100)
    )
    _spend(ledger, "alice", 90)  # 90% -> warn (default warn 80)
    _, out = _run("budgets", _session(ledger))  # alias
    assert "alice" in out and "90" in out and "warn" in out


def test_list_shows_company_wide_spend(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bpc"), scope_type=BudgetScope.COMPANY, scope_id="acme", amount=1000)
    )
    _spend(ledger, "alice", 300)  # any employee's spend counts toward the company cap
    _, out = _run("budget", _session(ledger))
    assert "company" in out and "300" in out


def test_list_marks_over(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bp1"), scope_type=BudgetScope.EMPLOYEE, scope_id="alice", amount=100)
    )
    _spend(ledger, "alice", 150)
    _, out = _run("budget list", _session(ledger))
    assert "over" in out


# -- raise / dismiss --------------------------------------------------------------------------------


def _pause(ledger: Ledger, session: CliSession) -> str:
    """Drive a hard breach so the employee scope is paused; return the policy id."""
    ledger.employees.create(Employee(id="alice", name="A", role="engineer"))
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bp1"), scope_type=BudgetScope.EMPLOYEE, scope_id="alice", amount=100)
    )
    _run("budget set employee alice 100", session)  # no-op (exists) — just keep ids stable
    _spend(ledger, "alice", 120)
    from chorus.budgets import BudgetEnforcer

    BudgetEnforcer(ledger, company_id="acme").on_cost_event(
        ledger.cost_events.get(uid("ce_120")),
        now=_NOW,  # type: ignore[arg-type]
    )
    return uid("bp1")


def test_raise_resumes_a_paused_scope(ledger: Ledger) -> None:
    session = _session(ledger)
    _pause(ledger, session)
    _, before = _run("budget", session)
    assert "paused" in before
    _, out = _run(f"budget raise {uid('bp1')} 200", session)
    assert f"raised {uid('bp1')}" in out
    _, after = _run("budget", session)
    assert "paused" not in after  # resumed


def test_raise_below_observed_errors(ledger: Ledger) -> None:
    session = _session(ledger)
    _pause(ledger, session)
    _, out = _run(f"budget raise {uid('bp1')} 50", session)  # 50 < observed 120
    assert "error:" in out and "exceed" in out


def test_raise_unknown_policy_errors(ledger: Ledger) -> None:
    _, out = _run(f"budget raise {uid('ghost')} 500", _session(ledger))
    assert "error:" in out and uid("ghost") in out


def test_raise_wrong_arity_reports_usage(ledger: Ledger) -> None:
    _, out = _run(f"budget raise {uid('bp1')}", _session(ledger))
    assert "usage: budget raise" in out


def test_raise_bad_amount_errors(ledger: Ledger) -> None:
    _, out = _run(f"budget raise {uid('bp1')} lots", _session(ledger))
    assert "error:" in out


def test_dismiss_wrong_arity_reports_usage(ledger: Ledger) -> None:
    _, out = _run("budget dismiss", _session(ledger))
    assert "usage: budget dismiss" in out


def test_dismiss_keeps_the_scope_paused(ledger: Ledger) -> None:
    session = _session(ledger)
    _pause(ledger, session)
    incident = ledger.budget_incidents.open_for_policy(uid("bp1"))[0]
    _, out = _run(f"budget dismiss {incident.id}", session)
    assert "dismissed" in out
    _, after = _run("budget", session)
    assert "paused" in after  # still paused


def test_dismiss_unknown_incident_errors(ledger: Ledger) -> None:
    _, out = _run(f"budget dismiss {uid('ghost')}", _session(ledger))
    assert "error:" in out


def test_unknown_subcommand_errors(ledger: Ledger) -> None:
    _, out = _run("budget frobnicate", _session(ledger))
    assert "error:" in out and "frobnicate" in out
