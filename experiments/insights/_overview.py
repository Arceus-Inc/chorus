"""The headline snapshot — one screen that says what this run did (spec 08 §3 status surface).

A direct projection over the ledger repos (no model, no scheduler): the roster, the task/beat rollup,
spend, and where the other spines live. The detailed sections are the sibling view modules.
"""

from __future__ import annotations

import json
from collections import Counter

from chorus.ledger import Run, SqliteLedger, TaskStatus
from experiments.insights import _render as r
from experiments.insights._sources import ExperimentSources

_TERMINAL = {TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED}


def render(sources: ExperimentSources) -> str:
    """The experiment at a glance: provenance, roster, work rollup, beats, and spend."""
    ledger = sources.ledger
    tasks = ledger.tasks.all()
    employees = ledger.employees.list()
    runs = [run for task in tasks for run in ledger.runs.for_task(task.id)]
    activities = ledger.activity.all()

    done = sum(1 for t in tasks if t.status is TaskStatus.DONE)
    blocked = sum(1 for t in tasks if t.status is TaskStatus.BLOCKED)
    open_tasks = sum(1 for t in tasks if t.status not in _TERMINAL)
    roster = Counter(e.role for e in employees)
    run_status = Counter(run.status.value for run in runs)
    spend = _spend(ledger, runs)

    lines = [
        r.header("EXPERIMENT INSIGHTS"),
        r.kv("ledger", f"{sources.db_path}  (schema {ledger.schema_version()})"),
        r.kv("events", sources.events_path or r.paint("not found", "grey")),
        r.kv("memory", sources.memory_dir or r.paint("not found", "grey")),
        "",
        r.kv(
            "roster",
            f"{len(employees)} employee(s)  ·  "
            + ("  ".join(f"{role}={n}" for role, n in roster.most_common()) or "—"),
        ),
        r.kv(
            "work",
            f"{len(tasks)} tasks  ·  {done} done  ·  {open_tasks} open  ·  "
            + r.status("blocked") + f"={blocked}  ·  {_rate(done, len(tasks))} complete",
        ),
        r.kv(
            "beats",
            f"{len(runs)} run(s)  ·  "
            + ("  ".join(f"{r.status(s)}={n}" for s, n in run_status.most_common()) or "—"),
        ),
        r.kv(
            "fan-out",
            f"{_verb(activities, 'decomposed')} decomposition(s)  ·  "
            f"{_verb(activities, 'assigned')} assignment(s)  ·  "
            f"{_verb(activities, 'review_verdict')} review verdict(s)",
        ),
        r.kv("spend", f"{spend} cents (${spend / 100:.2f})"),
    ]
    return "\n".join(lines)


def _spend(ledger: SqliteLedger, runs: list[Run]) -> int:
    """Total spend — the cost-event ledger if populated, else summed from run outcomes."""
    try:
        recorded = ledger.cost_events.total_spent_cents()
    except Exception:
        recorded = 0
    return recorded or sum(_run_cost(run) for run in runs)


def _run_cost(run: Run) -> int:
    outcome: object = run.outcome
    if isinstance(outcome, str):
        try:
            outcome = json.loads(outcome)
        except json.JSONDecodeError:
            return 0
    return int(outcome.get("cost_cents", 0)) if isinstance(outcome, dict) else 0


def _verb(activities: list, name: str) -> int:  # type: ignore[type-arg]
    return sum(1 for a in activities if a.verb.value == name)


def _rate(numerator: int, denominator: int) -> str:
    return f"{(numerator / denominator if denominator else 0.0):.0%}"


__all__ = ["render"]
