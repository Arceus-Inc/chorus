"""Task-ledger view — the durable DAG of work at a glance (spec 01 Cluster A).

One row per task: who owns it, its lifecycle status, how many beats it cost, its DoD verdict, and the
artifact it landed. This is the flat read of ``ledger.tasks.all()`` — the tree shape is
:mod:`experiments.insights._decomposition`.
"""

from __future__ import annotations

import json
from collections import Counter

from chorus.ledger import Run, SqliteLedger, Task
from experiments.insights import _render as r
from experiments.insights._sources import ExperimentSources


def render(sources: ExperimentSources) -> str:
    """The task ledger as a status rollup + a per-task table."""
    ledger = sources.ledger
    tasks = sorted(ledger.tasks.all(), key=_order_key)
    if not tasks:
        return r.header("TASK LEDGER") + "\n  (no tasks recorded)"

    roles = {e.id: e.role for e in ledger.employees.list()}
    rows = [_row(ledger, task, roles) for task in tasks]
    rollup = Counter(task.status.value for task in tasks)
    summary = "  ".join(f"{r.status(name)}={count}" for name, count in sorted(rollup.items()))

    headers = ("task", "assignee", "role", "status", "d", "beats", "¢", "dod", "artifact", "intent")
    return "\n".join(
        [
            r.header("TASK LEDGER"),
            r.kv("tasks", f"{len(tasks)}  ({summary})"),
            "",
            r.table(headers, rows),
        ]
    )


def _row(ledger: SqliteLedger, task: Task, roles: dict[str, str]) -> tuple[str, ...]:
    runs = ledger.runs.for_task(task.id)
    dod = ledger.dod.get_for_task(task.id)
    artifacts = ledger.artifacts.list_for_task(task.id)
    primary = next((a for a in artifacts if a.is_primary), artifacts[0] if artifacts else None)
    cost = sum(_run_cost(run) for run in runs)
    return (
        r.truncate(task.id, 14),
        task.assignee_employee_id or r.paint("—", "grey"),
        roles.get(task.assignee_employee_id or "", r.paint("—", "grey")),
        r.status(task.status.value),
        str(task.depth),
        str(len(runs)),
        str(cost) if cost else r.paint("0", "grey"),
        r.status(dod.status.value) if dod is not None else r.paint("—", "grey"),
        primary.type.value if primary is not None else r.paint("—", "grey"),
        r.truncate(task.intent, 40),
    )


def _order_key(task: Task) -> tuple[int, str]:
    return (task.depth, task.created_at.isoformat() if task.created_at else task.id)


def _run_cost(run: Run) -> int:
    """Beat cost in cents, read verbatim from the run outcome (mirrors the long-run probes)."""
    outcome: object = run.outcome
    if isinstance(outcome, str):
        try:
            outcome = json.loads(outcome)
        except json.JSONDecodeError:
            return 0
    return int(outcome.get("cost_cents", 0)) if isinstance(outcome, dict) else 0


__all__ = ["render"]
