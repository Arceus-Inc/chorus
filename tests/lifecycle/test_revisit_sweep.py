"""revisit_sweep — reopen decisions whose revisit window has elapsed (pm design doc §13).

A deterministic maintenance scan (no model in the loop): it walks the decision log and, for each
decision older than the revisit window that isn't superseded and hasn't already been reopened, submits
a fresh problem task assigned to the decision's original owner. Idempotent — a decision reopens once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.ledger._models import DecisionRecord
from chorus.lifecycle import revisit_sweep
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
_WINDOW = timedelta(days=14)


def _seed_decision(
    ledger: SqliteLedger,
    *,
    dec_id: str,
    task_id: str,
    age_days: int,
    assignee: str | None = "piper",
    superseded: bool = False,
) -> None:
    ledger.tasks.submit(
        Task(
            id=task_id,
            intent="decide next bet",
            status=TaskStatus.DONE,
            assignee_employee_id=assignee,
        )
    )
    ledger.decisions.create(
        DecisionRecord(
            id=dec_id,
            task_id=task_id,
            option="Build live presence indicators",
            rationale="run opacity is the top complaint",
            confidence=0.8,
            outcome_metric="'stuck' tickets drop 30%",
            revisit_trigger="if flat in 2 weeks, reopen",
            superseded_by="dec_successor" if superseded else None,
            created_at=_NOW - timedelta(days=age_days),
        )
    )


def _ledger_with_pm() -> SqliteLedger:
    ledger = SqliteLedger.open(":memory:")
    ledger.employees.create(Employee(id="piper", name="Piper", role="pm"))
    return ledger


def test_reopens_a_decision_past_its_revisit_window() -> None:
    ledger = _ledger_with_pm()
    _seed_decision(ledger, dec_id="dec_old", task_id="t-old", age_days=20)

    reopened = revisit_sweep(ledger, now=_NOW, window=_WINDOW)

    assert reopened == ["revisit-dec_old"]
    task = ledger.tasks.get("revisit-dec_old")
    assert task is not None
    assert task.status is TaskStatus.TODO
    assert task.assignee_employee_id == "piper"  # the decision's original owner
    assert "dec_old" in task.intent and "'stuck' tickets drop 30%" in task.intent
    ledger.close()


def test_does_not_reopen_a_recent_decision() -> None:
    ledger = _ledger_with_pm()
    _seed_decision(ledger, dec_id="dec_new", task_id="t-new", age_days=2)

    assert revisit_sweep(ledger, now=_NOW, window=_WINDOW) == []
    assert ledger.tasks.get("revisit-dec_new") is None
    ledger.close()


def test_does_not_reopen_a_superseded_decision() -> None:
    ledger = _ledger_with_pm()
    _seed_decision(ledger, dec_id="dec_sup", task_id="t-sup", age_days=30, superseded=True)

    assert revisit_sweep(ledger, now=_NOW, window=_WINDOW) == []
    assert ledger.tasks.get("revisit-dec_sup") is None
    ledger.close()


def test_is_idempotent_across_sweeps() -> None:
    ledger = _ledger_with_pm()
    _seed_decision(ledger, dec_id="dec_old", task_id="t-old", age_days=20)

    first = revisit_sweep(ledger, now=_NOW, window=_WINDOW)
    second = revisit_sweep(ledger, now=_NOW + timedelta(days=1), window=_WINDOW)

    assert first == ["revisit-dec_old"]
    assert second == []  # already reopened — no duplicate
    ledger.close()


def test_skips_a_decision_whose_owner_is_gone() -> None:
    ledger = _ledger_with_pm()
    _seed_decision(ledger, dec_id="dec_orphan", task_id="t-orphan", age_days=20, assignee=None)

    assert revisit_sweep(ledger, now=_NOW, window=_WINDOW) == []
    ledger.close()
