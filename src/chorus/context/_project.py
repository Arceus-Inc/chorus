"""Project a :class:`TaskContextPacket` from durable ledger rows.

One function, no model call, no mutation, no network. Every source it reads already exists — this
adds no storage, it delivers what the company is already writing on every beat.

Fail-soft by construction: the episodic store and the worktree are *enrichment*. A company without
them still gets the why-chain, the contract, the inbox and the budget, because a thin packet beats
no packet. Nothing in here may raise on a company that is merely young.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chorus.context._packet import (
    DEFAULT_MAX_PRIOR_BEATS,
    SUMMARY_CAP_CHARS,
    BudgetPosition,
    Contract,
    GoalLink,
    InboxItem,
    PriorBeat,
    TaskContextPacket,
)

if TYPE_CHECKING:
    from chorus.ledger import Ledger, Run, Task
    from chorus.memory import EpisodicStore
    from chorus.workforce import Employee

# Keys dream writes into ``run.outcome`` that carry an evaluator finding worth re-reading. The
# landed record (Phase 0) is nested under "landed" and read separately.
_VERDICT_KEYS = ("sprint_outcomes", "subagent_evidence_reason", "error")

_MAX_ANCESTOR_DEPTH = 32
"""Cycle guard. A parent chain is a DAG by construction, but a corrupt row must not hang a beat."""


def project_task_context(
    ledger: Ledger,
    *,
    task_id: str,
    run_id: str,
    employee: Employee,
    episodic: EpisodicStore | None = None,
    worktree: Path | None = None,
    max_prior_beats: int = DEFAULT_MAX_PRIOR_BEATS,
) -> TaskContextPacket:
    """Build the packet for one beat.

    ``episodic`` and ``worktree`` are optional enrichment (see module docstring). ``max_prior_beats``
    bounds the projection itself; the renderer applies its own token budget on top.

    Raises ``KeyError`` if the task does not exist — that is a kernel bug, not a young company, and
    silently projecting an empty packet would hide it.
    """
    task = ledger.tasks.get(task_id)
    if task is None:
        raise KeyError(task_id)

    runs = ledger.runs.for_task(task_id)
    return TaskContextPacket(
        task_id=task_id,
        run_id=run_id,
        employee_id=employee.id,
        role=employee.role,
        what=_contract(ledger, task),
        why=_why_chain(ledger, task),
        prior_beats=_prior_beats(
            ledger,
            runs=runs,
            current_run_id=run_id,
            episodic=episodic,
            worktree=worktree,
            limit=max_prior_beats,
        ),
        inbox=_inbox(ledger, employee),
        budget=_budget(ledger, employee=employee, beat_count=len(runs)),
    )


def _contract(ledger: Ledger, task: Task) -> Contract:
    """The task's own intent plus its DoD, verbatim."""
    verifier = ledger.dod.verifier_for_task(task.id)
    if verifier is None:
        return Contract(intent=task.intent)
    steps = verifier.verification_steps()
    # A Command DoD's "spec" is the command the oracle will actually run; an AgentReview's is the
    # rubric the evaluator judges against. Both are the literal text of the gate.
    spec = steps[0].command if steps else verifier.rubric()
    return Contract(
        intent=task.intent,
        dod_kind=verifier.kind.value,
        dod_spec=spec,
        artifact_class=verifier.artifact_class,
    )


def _why_chain(ledger: Ledger, task: Task) -> tuple[GoalLink, ...]:
    """Goals above this task, then the tasks that delegated to it — root first, both times.

    Root-first because that is the order a human explains work in: the company objective, then the
    narrowing, then your part. Reversing it buries the "why" under the "what".
    """
    return (*_goal_links(ledger, task.goal_id), *_ancestor_task_links(ledger, task))


def _goal_links(ledger: Ledger, goal_id: str | None) -> tuple[GoalLink, ...]:
    links: list[GoalLink] = []
    seen: set[str] = set()
    current = goal_id
    while current is not None and current not in seen and len(seen) < _MAX_ANCESTOR_DEPTH:
        seen.add(current)
        goal = ledger.goals.get(current)
        if goal is None:
            break
        links.append(GoalLink(kind="goal", id=goal.id, title=goal.title, status=goal.status))
        current = goal.parent_id
    return tuple(reversed(links))


def _ancestor_task_links(ledger: Ledger, task: Task) -> tuple[GoalLink, ...]:
    links: list[GoalLink] = []
    seen = {task.id}
    current = task.parent_id
    while current is not None and current not in seen and len(seen) < _MAX_ANCESTOR_DEPTH:
        seen.add(current)
        parent = ledger.tasks.get(current)
        if parent is None:
            break
        links.append(
            GoalLink(kind="task", id=parent.id, title=parent.intent, status=parent.status.value)
        )
        current = parent.parent_id
    return tuple(reversed(links))


def _prior_beats(
    ledger: Ledger,
    *,
    runs: list[Run],
    current_run_id: str,
    episodic: EpisodicStore | None,
    worktree: Path | None,
    limit: int,
) -> tuple[PriorBeat, ...]:
    """Previous runs on this task, oldest first, bounded to the most recent ``limit``.

    ``runs`` arrives oldest-first from the repo; numbering uses that full ordering so a beat's
    number is stable even when older beats fall outside the window.
    """
    prior = [
        (number, run)
        for number, run in enumerate(runs, start=1)
        if run.id != current_run_id and run.finished_at is not None
    ]
    return tuple(
        _prior_beat(run, beat_number=number, episodic=episodic, worktree=worktree)
        for number, run in prior[-limit:]
    )


def _prior_beat(
    run: Run,
    *,
    beat_number: int,
    episodic: EpisodicStore | None,
    worktree: Path | None,
) -> PriorBeat:
    landed = run.outcome.get("landed")
    landed_map: dict[str, Any] = landed if isinstance(landed, dict) else {}
    delta = _episodic_record(episodic, run.id)
    return PriorBeat(
        run_id=run.id,
        beat_number=beat_number,
        employee_id=run.employee_id,
        status=run.status.value,
        phase=_opt_str(landed_map.get("phase")),
        recovery_hint=_opt_str(landed_map.get("recovery_hint")),
        passed=landed_map.get("passed") if isinstance(landed_map.get("passed"), bool) else None,
        outcome=delta.outcome if delta is not None else "",
        score=delta.score if delta is not None else 0.0,
        files_touched=delta.files_touched if delta is not None else (),
        artifacts=delta.artifacts if delta is not None else (),
        verdict_notes=_verdict_notes(run, worktree=worktree, landed=landed_map),
        summary=_summary(run, delta_body=delta.body if delta is not None else ""),
    )


def _episodic_record(episodic: EpisodicStore | None, run_id: str) -> Any:
    """The episodic delta for a run, or ``None``. A missing store is normal, not an error."""
    if episodic is None:
        return None
    try:
        return episodic.get(run_id)
    except Exception:  # a broken episodic store must never take down a beat's context
        return None


def _verdict_notes(run: Run, *, worktree: Path | None, landed: dict[str, Any]) -> tuple[str, ...]:
    """What the evaluator actually said about this beat.

    Two sources, deliberately in this order:

    1. ``run.outcome`` — employee-agnostic, always present. Survives task reassignment.
    2. ``docs/evals/<run_id>/sprint-*.json`` in the worktree — richer prose, but only resolves when
       the prior beat ran in *this* worktree. A reassigned task finds nothing here, which is exactly
       why source 1 leads.
    """
    notes: list[str] = []
    diagnostic = _opt_str(landed.get("diagnostic"))
    if diagnostic:
        notes.append(diagnostic)
    for key in _VERDICT_KEYS:
        value = run.outcome.get(key)
        if value:
            notes.append(f"{key}: {value}")
    notes.extend(_eval_notes(worktree, run.id))
    return tuple(dict.fromkeys(notes))  # de-dup, order-preserving


def _eval_notes(worktree: Path | None, run_id: str) -> list[str]:
    if worktree is None:
        return []
    notes: list[str] = []
    for path in sorted((worktree / "docs" / "evals" / run_id).glob("sprint-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        note = str(record.get("notes", "")).strip() if isinstance(record, dict) else ""
        if note:
            notes.append(f"{path.name}: {note}")
    return notes


def _summary(run: Run, *, delta_body: str) -> str:
    """The beat's own account, capped. Falls back to the landed summary when episodic is absent."""
    if delta_body:
        return _cap(delta_body)
    landed = run.outcome.get("landed")
    if isinstance(landed, dict):
        return _cap(_opt_str(landed.get("summary")) or "")
    return ""


def _cap(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= SUMMARY_CAP_CHARS:
        return stripped
    return stripped[: SUMMARY_CAP_CHARS - 1].rstrip() + "…"


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _inbox(ledger: Ledger, employee: Employee) -> tuple[InboxItem, ...]:
    """Unread messages for this employee.

    Read-only: the packet projects the inbox, it does not consume it. Marking read is a side effect
    and belongs at the injection site, where it can be paired with the beat actually starting.
    """
    return tuple(
        InboxItem(
            message_id=message.id,
            from_id=message.from_employee_id or message.from_user_id or "unknown",
            body=message.body,
            task_id=message.task_id,
        )
        for message in ledger.messages.inbox(employee.id)
    )


def _budget(ledger: Ledger, *, employee: Employee, beat_count: int) -> BudgetPosition:
    return BudgetPosition(
        spent_cents=ledger.cost_events.spent_cents(employee.id),
        limit_cents=employee.budget_monthly_cents,
        beat_number=beat_count,
    )


__all__ = ["project_task_context"]
