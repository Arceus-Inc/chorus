"""The task status machine (spec 02 §2).

Pins the legal transition table, terminal states, entry-timestamp stamping, and
the load-bearing rule that **entering ``in_progress`` happens by checkout, never
by a bare status PATCH**. Pure-machine cases need no DB; the repo cases drive the
guard end-to-end through ``TaskRepo.transition``.
"""

from __future__ import annotations

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import (
    IllegalTransition,
    assert_legal,
    entry_stamp,
    is_legal,
)
from chorus.workforce import Employee

# The authoritative edges (spec 02 §2) — pinned here, independently of the module.
_LEGAL: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.BACKLOG: {TaskStatus.TODO, TaskStatus.CANCELLED},
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {
        TaskStatus.IN_REVIEW,
        TaskStatus.BLOCKED,
        TaskStatus.DONE,
        TaskStatus.CANCELLED,
        TaskStatus.REJECTED,
    },
    TaskStatus.IN_REVIEW: {
        TaskStatus.IN_PROGRESS,
        TaskStatus.DONE,
        TaskStatus.CANCELLED,
        TaskStatus.REJECTED,
    },
    TaskStatus.BLOCKED: {
        TaskStatus.TODO,
        TaskStatus.IN_PROGRESS,
        TaskStatus.CANCELLED,
        TaskStatus.REJECTED,
    },
    TaskStatus.DONE: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.REJECTED: set(),
}

_ALL = list(TaskStatus)
_LEGAL_PAIRS = [(s, t) for s, ts in _LEGAL.items() for t in ts]
_ILLEGAL_PAIRS = [(s, t) for s in _ALL for t in _ALL if t not in _LEGAL[s]]


# -- the pure machine ---------------------------------------------------------


@pytest.mark.parametrize(("src", "dst"), _LEGAL_PAIRS)
def test_legal_edges_pass(src: TaskStatus, dst: TaskStatus) -> None:
    assert is_legal(src, dst)
    # via_checkout exercises the in_progress edges; it must not reject a legal edge.
    assert_legal(src, dst, via_checkout=True)


@pytest.mark.parametrize(("src", "dst"), _ILLEGAL_PAIRS)
def test_illegal_edges_rejected(src: TaskStatus, dst: TaskStatus) -> None:
    assert not is_legal(src, dst)
    with pytest.raises(IllegalTransition):
        assert_legal(src, dst, via_checkout=True)


@pytest.mark.parametrize("terminal", [TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED])
def test_terminal_states_have_no_exit(terminal: TaskStatus) -> None:
    assert not _LEGAL[terminal]
    for dst in _ALL:
        assert not is_legal(terminal, dst)


def test_self_transition_is_illegal() -> None:
    for s in _ALL:
        assert not is_legal(s, s)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (TaskStatus.IN_PROGRESS, "started_at"),
        (TaskStatus.DONE, "completed_at"),
        (TaskStatus.CANCELLED, "cancelled_at"),
        (TaskStatus.BACKLOG, None),
        (TaskStatus.TODO, None),
        (TaskStatus.IN_REVIEW, None),
        (TaskStatus.BLOCKED, None),
    ],
)
def test_entry_stamp_mapping(status: TaskStatus, expected: str | None) -> None:
    assert entry_stamp(status) == expected


def test_bare_patch_into_in_progress_is_rejected() -> None:
    # The edge is legal, but only checkout may take it (spec 02 §2).
    with pytest.raises(IllegalTransition):
        assert_legal(TaskStatus.TODO, TaskStatus.IN_PROGRESS, via_checkout=False)
    with pytest.raises(IllegalTransition):
        assert_legal(TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS, via_checkout=False)
    # checkout is the sanctioned path.
    assert_legal(TaskStatus.TODO, TaskStatus.IN_PROGRESS, via_checkout=True)


# -- the guarded repo seam ----------------------------------------------------


def _submit(ledger: SqliteLedger, status: TaskStatus) -> Task:
    return ledger.tasks.submit(Task(id="t1", intent="ship it", status=status))


def test_transition_todo_to_blocked(ledger: SqliteLedger) -> None:
    _submit(ledger, TaskStatus.TODO)
    ledger.tasks.transition("t1", TaskStatus.BLOCKED)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.BLOCKED
    assert task.started_at is None  # blocked stamps nothing


def test_transition_into_in_progress_requires_checkout(ledger: SqliteLedger) -> None:
    _submit(ledger, TaskStatus.TODO)
    with pytest.raises(IllegalTransition):
        ledger.tasks.transition("t1", TaskStatus.IN_PROGRESS)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.TODO  # rejected, unchanged


def test_checkout_then_transition_to_done_stamps_completed(
    ledger: SqliteLedger, employee: Employee
) -> None:
    _submit(ledger, TaskStatus.TODO)
    assert ledger.tasks.checkout("t1", employee_id=employee.id, run_id="run_1")
    ledger.tasks.transition("t1", TaskStatus.DONE)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.DONE
    assert task.started_at is not None
    assert task.completed_at is not None


def test_transition_to_cancelled_stamps_cancelled_at(ledger: SqliteLedger) -> None:
    _submit(ledger, TaskStatus.TODO)
    ledger.tasks.transition("t1", TaskStatus.CANCELLED)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.CANCELLED
    assert task.cancelled_at is not None


def test_transition_from_terminal_is_rejected(ledger: SqliteLedger) -> None:
    _submit(ledger, TaskStatus.DONE)
    with pytest.raises(IllegalTransition):
        ledger.tasks.transition("t1", TaskStatus.TODO)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.DONE  # terminal, unchanged


def test_transition_unknown_task_raises(ledger: SqliteLedger) -> None:
    with pytest.raises(KeyError):
        ledger.tasks.transition("nope", TaskStatus.TODO)
