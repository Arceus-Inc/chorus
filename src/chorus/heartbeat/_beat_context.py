"""The per-beat context a capability tool needs but dream's ``ToolExecutionContext`` does not carry.

A capability tool (e.g. ``decompose``) runs *inside* a dream beat and must know which task and run it
is acting for. The harness is materialized per-employee (``runner_for(employee)``) — it does not see
the beat's ``task_id`` / ``run_id`` — so the kernel writes those to a small file in the employee's
working dir just before the beat, and the tool reads it back from ``ctx.working_dir``.

Dream-free (chorus core): both the writer (the kernel) and the reader (a ``chorus_tools`` tool) share
this one model so the on-disk shape can't drift between them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chorus.ledger._models import ActivityVerb, TaskStatus
from chorus.lifecycle._audit import record_activity

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

_RELATIVE_PATH = Path(".harness") / "beat-context.json"
_INTEGRATE_RELATIVE_PATH = Path(".harness") / "integrate-context.json"


@dataclass(frozen=True)
class BeatContext:
    """Which task/run an employee's beat is acting for, handed to its in-beat capability tools."""

    task_id: str
    run_id: str
    employee_id: str

    @staticmethod
    def path_in(working_dir: Path) -> Path:
        """The on-disk location of the beat context under an employee's working dir."""
        return working_dir / _RELATIVE_PATH

    def write(self, working_dir: Path) -> None:
        """Persist this context under ``working_dir`` for the beat's capability tools to read."""
        path = self.path_in(working_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": self.task_id, "run_id": self.run_id, "employee_id": self.employee_id}
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def read(cls, working_dir: Path) -> BeatContext:
        """Load the beat context a tool is acting under; raises if it is missing or malformed."""
        data = json.loads(cls.path_in(working_dir).read_text(encoding="utf-8"))
        return cls(
            task_id=data["task_id"],
            run_id=data["run_id"],
            employee_id=data["employee_id"],
        )


@dataclass(frozen=True)
class ReportContext:
    """One direct report available to a manager for routing follow-up work."""

    id: str
    role: str
    status: str


@dataclass(frozen=True)
class ChildOutcomeContext:
    """One child row in the manager's integrate/scrum packet."""

    task_id: str
    label: str
    intent: str
    assignee: str | None
    assignee_role: str | None
    status: str
    blockers: tuple[str, ...]
    dod_status: str | None
    dod_verdict: dict[str, object] | None
    latest_run_id: str | None
    latest_run_status: str | None
    latest_run_summary: str | None
    latest_run_outcome: dict[str, object] | None
    artifact_type: str | None
    artifact_ref: dict[str, object] | None


@dataclass(frozen=True)
class IntegrateContextPacket:
    """The manager's scrum packet: parent goal, reports, and child feedback."""

    parent_task_id: str
    parent_intent: str
    iteration: int
    available_reports: tuple[ReportContext, ...]
    children: tuple[ChildOutcomeContext, ...]

    @staticmethod
    def path_in(working_dir: Path) -> Path:
        """The on-disk location of the integrate packet under an employee's working dir."""
        return working_dir / _INTEGRATE_RELATIVE_PATH

    @staticmethod
    def iteration_for(ledger: SqliteLedger, parent_task_id: str) -> int:
        """1-based count of integrate beats this parent has had (its runs minus the kickoff beat).

        The single source of truth for the loop depth — used both by the kernel (to write the packet
        and enforce the integrate cap) and by the inspector (so ``check scrum`` reports the real count).
        """
        return max(1, len(ledger.runs.for_task(parent_task_id)) - 1)

    @classmethod
    def build(
        cls, ledger: SqliteLedger, *, parent_task_id: str, audit: bool = True
    ) -> IntegrateContextPacket:
        """Build the packet from durable ledger state for the manager's integrate beat."""
        parent = ledger.tasks.get(parent_task_id)
        if parent is None:
            raise KeyError(parent_task_id)
        iteration = cls.iteration_for(ledger, parent_task_id)
        manager_id = parent.assignee_employee_id
        reports = tuple(
            ReportContext(id=emp.id, role=emp.role, status=emp.status.value)
            for emp in ledger.employees.list()
            if manager_id is not None and emp.reports_to == manager_id
        )
        children = tuple(_child_outcome(ledger, child.id) for child in ledger.tasks.children(parent_task_id))
        packet = cls(
            parent_task_id=parent.id,
            parent_intent=parent.intent,
            iteration=iteration,
            available_reports=reports,
            children=children,
        )
        if audit:
            record_activity(
                ledger,
                verb=ActivityVerb.SCRUM_PACKET,
                subject_id=parent.id,
                actor_employee_id=manager_id,
                payload={
                    "iteration": iteration,
                    "child_count": len(children),
                    "completed_children": sum(
                        1 for child in children if child.status in {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}
                    ),
                    "blocked_children": sum(1 for child in children if child.blockers),
                    "direct_reports": [report.id for report in reports],
                },
            )
        return packet

    def write(self, working_dir: Path) -> None:
        """Persist this packet for the manager integrate beat to read."""
        path = self.path_in(working_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self)), encoding="utf-8")

    @classmethod
    def read(cls, working_dir: Path) -> IntegrateContextPacket:
        """Load a persisted integrate packet."""
        data = json.loads(cls.path_in(working_dir).read_text(encoding="utf-8"))
        return cls(
            parent_task_id=data["parent_task_id"],
            parent_intent=data["parent_intent"],
            iteration=int(data["iteration"]),
            available_reports=tuple(ReportContext(**item) for item in data["available_reports"]),
            children=tuple(ChildOutcomeContext(**item) for item in data["children"]),
        )


def _child_outcome(ledger: SqliteLedger, task_id: str) -> ChildOutcomeContext:
    task = ledger.tasks.get(task_id)
    if task is None:
        raise KeyError(task_id)
    assignee = ledger.employees.get(task.assignee_employee_id) if task.assignee_employee_id else None
    dod = ledger.dod.get_for_task(task.id)
    runs = ledger.runs.for_task(task.id)
    latest_run = runs[-1] if runs else None
    artifact = _primary_artifact(ledger.artifacts.list_for_task(task.id))
    outcome = latest_run.outcome if latest_run is not None else None
    return ChildOutcomeContext(
        task_id=task.id,
        label=task.origin_fingerprint,
        intent=task.intent,
        assignee=task.assignee_employee_id,
        assignee_role=assignee.role if assignee is not None else None,
        status=task.status.value,
        blockers=tuple(ledger.dependencies.blockers(task.id)),
        dod_status=dod.status.value if dod is not None else None,
        dod_verdict=dod.verdict if dod is not None else None,
        latest_run_id=latest_run.id if latest_run is not None else None,
        latest_run_status=latest_run.status.value if latest_run is not None else None,
        latest_run_summary=_summary(outcome),
        latest_run_outcome=outcome,
        artifact_type=artifact.type.value if artifact is not None else None,
        artifact_ref=artifact.resource_ref if artifact is not None else None,
    )


def _primary_artifact(artifacts: list[Any]) -> Any | None:
    primaries = [artifact for artifact in artifacts if artifact.is_primary]
    if primaries:
        return primaries[-1]
    return artifacts[-1] if artifacts else None


def _summary(outcome: dict[str, object] | None) -> str | None:
    if outcome is None:
        return None
    value = outcome.get("summary")
    return value if isinstance(value, str) else None


__all__ = ["BeatContext", "ChildOutcomeContext", "IntegrateContextPacket", "ReportContext"]
