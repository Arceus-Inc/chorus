"""The inspector — a pure read model over the ledger + event log (spec 08 §3).

Holds no state. Surfaces (Paperclip's layered liveness UI, adapted): the live
beat surface (from the ``run.*`` stream), the liveness vocabulary (straight from
``run.evaluated``), recovery cards (one per open ``recovery_action``), and the
blocked inbox (every stalled task, ranked). The CLI ``chorus inspect`` and (in
Arceus) the web board are both views over this projection.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chorus.heartbeat import IntegrateContextPacket
from chorus.ledger import ActivityVerb, RunStatus, TaskStatus
from chorus.observability._views import (
    OrgObservabilityReport,
    ScrumChildView,
    ScrumPacketView,
    TaskView,
    WorkforceStatus,
)

if False:  # pragma: no cover - typing only without runtime import cost
    from chorus.ledger import SqliteLedger


@runtime_checkable
class Inspector(Protocol):
    """The read-model contract (spec 09 §4) — swappable behind the facade."""

    def status(self) -> WorkforceStatus:
        """The company at a glance — employees, open tasks, runs, incidents."""
        ...

    def task(self, task_id: str) -> TaskView:
        """One task, resolved (names + liveness + blockers)."""
        ...

    def stuck(self) -> list[TaskView]:
        """The blocked inbox — non-terminal tasks with no action-path primitive (spec 08 §2)."""
        ...

    def scrum_packet(self, parent_task_id: str) -> ScrumPacketView:
        """Manager packet rollup for one delegated parent task."""
        ...

    def org_report(self) -> OrgObservabilityReport:
        """Combined manager + leaf observability rollup."""
        ...


class LedgerInspector:
    """The default :class:`Inspector` over the SQLite ledger + event log (spec 08 §3)."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def status(self) -> WorkforceStatus:
        raise NotImplementedError("spec 08 §3: project employees/tasks/runs/incidents")

    def task(self, task_id: str) -> TaskView:
        raise NotImplementedError("spec 08 §3: resolve names + derive liveness + blockers")

    def stuck(self) -> list[TaskView]:
        raise NotImplementedError("spec 08 §2: the stuck query (non-terminal, no live path)")

    def scrum_packet(self, parent_task_id: str) -> ScrumPacketView:
        parent = self._ledger.tasks.get(parent_task_id)
        if parent is None:
            raise KeyError(parent_task_id)
        packet = IntegrateContextPacket.build(
            self._ledger, parent_task_id=parent_task_id, audit=False
        )
        assignment_count = 0
        reassignment_count = 0
        for child in packet.children:
            for activity in self._ledger.activity.by_subject("task", child.task_id):
                if activity.verb is ActivityVerb.ASSIGNED:
                    assignment_count += 1
                    if activity.payload.get("reassigned") is True:
                        reassignment_count += 1
        parent_edges = len(self._ledger.dependencies.blockers(parent_task_id))
        child_edges = sum(len(child.blockers) for child in packet.children)
        completed = sum(1 for child in packet.children if child.status in _TERMINAL_STATUS_VALUES)
        blocked = sum(1 for child in packet.children if child.blockers)
        total = len(packet.children)
        return ScrumPacketView(
            parent_task_id=parent.id,
            parent_intent=parent.intent,
            manager_id=parent.assignee_employee_id,
            iteration=packet.iteration,
            recommended_action=packet.recommended_action,
            child_count=total,
            completed_children=completed,
            blocked_children=blocked,
            dependency_edges=parent_edges + child_edges,
            assignment_count=assignment_count,
            reassignments=reassignment_count,
            completion_rate=_rate(completed, total),
            children=tuple(
                ScrumChildView(
                    task_id=child.task_id,
                    label=child.label,
                    assignee=child.assignee,
                    assignee_role=child.assignee_role,
                    status=child.status,
                    blockers=child.blockers,
                    dod_status=child.dod_status,
                    latest_run_status=child.latest_run_status,
                    latest_run_summary=child.latest_run_summary,
                    artifact_type=child.artifact_type,
                )
                for child in packet.children
            ),
        )

    def org_report(self) -> OrgObservabilityReport:
        employees = self._ledger.employees.list()
        manager_ids = {employee.reports_to for employee in employees if employee.reports_to is not None}
        tasks = self._ledger.tasks.all()
        activities = self._ledger.activity.all()
        assignment_activities = [a for a in activities if a.verb is ActivityVerb.ASSIGNED]
        packets = tuple(self.scrum_packet(task.id) for task in tasks if self._ledger.tasks.has_children(task.id))
        runs = [run for task in tasks for run in self._ledger.runs.for_task(task.id)]
        done = sum(1 for task in tasks if task.status is TaskStatus.DONE)
        return OrgObservabilityReport(
            employees=len(employees),
            managers=len(manager_ids),
            leaves=len(employees) - len(manager_ids),
            tasks_total=len(tasks),
            tasks_done=done,
            tasks_blocked=sum(1 for task in tasks if task.status is TaskStatus.BLOCKED),
            running_beats=sum(1 for run in runs if run.status is RunStatus.RUNNING),
            failed_runs=sum(1 for run in runs if run.status in _FAILED_RUN_STATUSES),
            completion_rate=_rate(done, len(tasks)),
            decomposition_count=sum(1 for a in activities if a.verb is ActivityVerb.DECOMPOSED),
            assignment_count=len(assignment_activities),
            reassignment_count=sum(1 for a in assignment_activities if a.payload.get("reassigned") is True),
            dependency_edges=sum(len(self._ledger.dependencies.blockers(task.id)) for task in tasks),
            manager_packets=packets,
        )


_TERMINAL_STATUS_VALUES = {
    TaskStatus.DONE.value,
    TaskStatus.CANCELLED.value,
    TaskStatus.REJECTED.value,
}
_FAILED_RUN_STATUSES = {RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CANCELLED}


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


__all__ = [
    "Inspector",
    "LedgerInspector",
]
