"""Deterministically project the typed task context from durable Chorus rows."""

from __future__ import annotations

from datetime import UTC, datetime

from chorus.budgets import BudgetWindow, window_start
from chorus.context._packet import (
    AncestryKind,
    AncestryLink,
    BudgetPosition,
    Citation,
    DoDRequirement,
    InboxItem,
    PriorBeat,
    SiblingFailure,
    TaskContextPacket,
    TaskContract,
    Truncation,
)
from chorus.ledger import BudgetScope, Ledger, Task, TaskStatus
from chorus.outcomes import AgentReview, Command, HumanApproval
from chorus.workforce import Employee

MAX_ANCESTRY = 32
MAX_INBOX = 20
MAX_PRIOR_BEATS = 4


def project_task_context(
    ledger: Ledger, *, task_id: str, employee: Employee, now: datetime | None = None
) -> TaskContextPacket:
    """Return the bounded, task-keyed briefing for one employee's next beat."""
    task = ledger.tasks.get(task_id)
    if task is None:
        raise KeyError(task_id)
    ancestry, ancestry_truncation = _ancestry(ledger, task)
    prior, prior_truncation = _prior_beats(ledger, task_id)
    inbox, inbox_truncation = _inbox(ledger, employee)
    sibling_failures, sibling_truncation = _sibling_failures(ledger, task)
    return TaskContextPacket(
        task_id=task.id,
        contract=_contract(ledger, task),
        ancestry=ancestry,
        prior_beats=prior,
        inbox=inbox,
        sibling_failures=sibling_failures,
        budget=_budget(ledger, employee, now or datetime.now(UTC), len(ledger.runs.for_task(task.id))),
        citations=(
            Citation(f"ledger.task:{task.id}", "assigned task and contract"),
            Citation(f"ledger.employee:{employee.id}", "recipient and budget scope"),
            *tuple(beat.citation for beat in prior),
            *tuple(failure.citation for failure in sibling_failures),
        ),
        truncation=tuple(
            item
            for item in (ancestry_truncation, prior_truncation, inbox_truncation, sibling_truncation)
            if item is not None
        ),
    )


def _contract(ledger: Ledger, task: Task) -> TaskContract:
    verifier = ledger.dod.verifier_for_task(task.id)
    if verifier is None:
        return TaskContract(intent=task.intent)
    spec = verifier.spec
    if isinstance(spec, Command):
        dod = (DoDRequirement("command", f"{spec.command} (timeout {spec.timeout_s}s)"),)
    elif isinstance(spec, AgentReview):
        dod = (DoDRequirement("agent_review", f"{spec.reviewer_role}: {spec.rubric}"),)
    elif isinstance(spec, HumanApproval):
        dod = (DoDRequirement("human_approval", f"approver: {spec.approver}"),)
    else:
        raise TypeError(f"unsupported verifier spec {type(spec)!r}")
    return TaskContract(intent=task.intent, dod=dod)


def _ancestry(ledger: Ledger, task: Task) -> tuple[tuple[AncestryLink, ...], Truncation | None]:
    goals: list[AncestryLink] = []
    seen_goals: set[str] = set()
    goal_id = task.goal_id
    while goal_id is not None and goal_id not in seen_goals and len(goals) < MAX_ANCESTRY:
        seen_goals.add(goal_id)
        goal = ledger.goals.get(goal_id)
        if goal is None:
            break
        goals.append(AncestryLink(AncestryKind.GOAL, goal.id, goal.title, goal.status))
        goal_id = goal.parent_id
    tasks: list[AncestryLink] = []
    seen_tasks = {task.id}
    parent_id = task.parent_id
    while (
        parent_id is not None
        and parent_id not in seen_tasks
        and len(goals) + len(tasks) < MAX_ANCESTRY
    ):
        seen_tasks.add(parent_id)
        parent = ledger.tasks.get(parent_id)
        if parent is None:
            break
        tasks.append(
            AncestryLink(AncestryKind.TASK, parent.id, parent.intent, parent.status.value)
        )
        parent_id = parent.parent_id
    links = tuple(reversed(goals)) + tuple(reversed(tasks))
    omitted = int(goal_id is not None or parent_id is not None)
    return links, _truncation("ancestry", omitted)


def _prior_beats(ledger: Ledger, task_id: str) -> tuple[tuple[PriorBeat, ...], Truncation | None]:
    carryovers = ledger.run_carryovers.for_task(task_id)
    omitted = max(0, len(carryovers) - MAX_PRIOR_BEATS)
    prior = tuple(
        PriorBeat(
            run_id=row.run_id,
            phase=row.phase,
            recovery_hint=row.recovery_hint,
            evaluator_notes=row.evaluator_notes,
            files_touched=row.files_touched,
            todo_digest=row.todo_digest,
            summary=row.summary,
            citation=Citation(f"ledger.run_carryover:{row.run_id}", "landed beat carryover"),
        )
        for row in carryovers[-MAX_PRIOR_BEATS:]
    )
    return prior, _truncation("prior_beats", omitted)


def _inbox(ledger: Ledger, employee: Employee) -> tuple[tuple[InboxItem, ...], Truncation | None]:
    messages = ledger.messages.inbox(employee.id)
    omitted = max(0, len(messages) - MAX_INBOX)
    return (
        tuple(
            InboxItem(
                id=message.id,
                sender=message.from_employee_id or message.from_user_id or "unknown",
                body=message.body,
                task_id=message.task_id,
            )
            for message in messages[-MAX_INBOX:]
        ),
        _truncation("inbox", omitted),
    )


def _budget(ledger: Ledger, employee: Employee, now: datetime, beat_count: int) -> BudgetPosition:
    policy = ledger.budget_policies.find(
        scope_type=BudgetScope.EMPLOYEE, scope_id=employee.id, window_kind=BudgetWindow.MONTHLY.value
    )
    limit = policy.amount if policy is not None else employee.budget_monthly_cents
    active_limit = limit if limit is not None and limit > 0 else None
    return BudgetPosition(
        spent_cents=ledger.cost_events.spent_cents(
            employee.id, since=window_start(BudgetWindow.MONTHLY, now)
        ),
        limit_cents=active_limit,
        beat_count=beat_count,
    )


def _sibling_failures(
    ledger: Ledger, task: Task
) -> tuple[tuple[SiblingFailure, ...], Truncation | None]:
    if task.parent_id is None or task.assignee_employee_id is None:
        return (), None
    failures: list[SiblingFailure] = []
    for sibling in ledger.tasks.children(task.parent_id):
        if sibling.id == task.id or sibling.assignee_employee_id != task.assignee_employee_id:
            continue
        if sibling.status not in {TaskStatus.REJECTED, TaskStatus.CANCELLED}:
            continue
        notes = tuple(
            note
            for carryover in ledger.run_carryovers.for_task(sibling.id)
            for note in carryover.evaluator_notes
        )
        if notes:
            failures.append(
                SiblingFailure(
                    task_id=sibling.id,
                    status=sibling.status.value,
                    notes=notes,
                    citation=Citation(
                        f"ledger.task:{sibling.id}", "same-assignee corrective sibling failure"
                    ),
                )
            )
    return tuple(sorted(failures, key=lambda failure: failure.task_id)), None


def _truncation(section: str, omitted: int) -> Truncation | None:
    if omitted == 0:
        return None
    return Truncation(section=section, omitted=omitted, reason="bounded deterministic projection")


__all__ = [
    "MAX_ANCESTRY",
    "MAX_INBOX",
    "MAX_PRIOR_BEATS",
    "project_task_context",
]
