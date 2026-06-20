"""Decomposition view — the manager→worker fan-out tree (spec 01 Cluster A, spec 03 §3).

Renders ``parent_id`` edges as an indented tree so you can see how a one-line goal was split into a
subtree of children, who each child landed with, and where the tree stalled. The flat table is
:mod:`experiments.insights._ledger`.
"""

from __future__ import annotations

from collections import defaultdict

from chorus.ledger import ActivityVerb, SqliteLedger, Task
from experiments.insights import _render as r
from experiments.insights._sources import ExperimentSources

_BRANCH, _LAST, _PIPE, _GAP = "├─ ", "└─ ", "│  ", "   "


def render(sources: ExperimentSources) -> str:
    """The work tree, plus a fan-out rollup (decompositions, assignments, reassignments)."""
    ledger = sources.ledger
    tasks = ledger.tasks.all()
    if not tasks:
        return r.header("DECOMPOSITION TREE") + "\n  (no tasks recorded)"

    roles = {e.id: e.role for e in ledger.employees.list()}
    children: dict[str | None, list[Task]] = defaultdict(list)
    for task in tasks:
        children[task.parent_id].append(task)
    for bucket in children.values():
        bucket.sort(key=lambda t: t.created_at.isoformat() if t.created_at else t.id)

    lines: list[str] = [r.header("DECOMPOSITION TREE"), _rollup(ledger, tasks), ""]
    roots = children.get(None, [])
    for index, root in enumerate(roots):
        _walk(root, children, roles, prefix="", last=index == len(roots) - 1, out=lines)
    return "\n".join(lines)


def _walk(
    task: Task,
    children: dict[str | None, list[Task]],
    roles: dict[str, str],
    *,
    prefix: str,
    last: bool,
    out: list[str],
) -> None:
    connector = "" if not prefix and task.parent_id is None else (_LAST if last else _BRANCH)
    out.append(prefix + connector + _node(task, roles, root=not prefix and task.parent_id is None))
    kids = children.get(task.id, [])
    child_prefix = prefix + ("" if connector == "" else (_GAP if last else _PIPE))
    for index, child in enumerate(kids):
        _walk(child, children, roles, prefix=child_prefix, last=index == len(kids) - 1, out=out)


def _node(task: Task, roles: dict[str, str], *, root: bool) -> str:
    who = task.assignee_employee_id or "—"
    role = roles.get(task.assignee_employee_id or "", "—")
    label = r.paint(r.truncate(task.id, 16), "bold" if root else "cyan")
    owner = r.paint(f"[{who}/{role}]", "grey")
    return f"{label} {r.status(task.status.value)} {owner}  {r.truncate(task.intent, 52)}"


def _rollup(ledger: SqliteLedger, tasks: list[Task]) -> str:
    activities = ledger.activity.all()
    fanouts = sum(1 for a in activities if a.verb is ActivityVerb.DECOMPOSED)
    assignments = [a for a in activities if a.verb is ActivityVerb.ASSIGNED]
    reassigned = sum(1 for a in assignments if a.payload.get("reassigned") is True)
    roots = sum(1 for t in tasks if t.parent_id is None)
    max_depth = max((t.depth for t in tasks), default=0)
    return r.kv(
        "shape",
        f"{roots} root(s)  ·  {len(tasks)} tasks  ·  max depth {max_depth}  ·  "
        f"{fanouts} decomposition(s)  ·  {len(assignments)} assignment(s) "
        f"({reassigned} reassigned)",
    )


__all__ = ["render"]
