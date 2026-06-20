"""Decomposition report generator — draw a chorus run's org chart + task tree from its ledger.

The ``standup-app`` run leaves behind one SQLite ledger (``company.db``) that is the single source of
truth for everything that happened: who was hired (``employee.reports_to`` = the org chart), how the
goal was split (``task.parent_id`` = the decomposition tree), who owns each task, and how every beat
landed. This script reads that ledger — nothing else — and renders:

    1. the ORG CHART          (Mermaid graph + a roster table)
    2. the DECOMPOSITION TREE (Mermaid graph, status-coloured + an indented text tree)
    3. a TASK TABLE           (id · depth · assignee/role · status · latest beat · intent)
    4. ROLLUP TOTALS          (employees by role, tasks by status, delegation/landing counts)

It imports only ``chorus.ledger`` (the public ledger types) — it never builds a company or talks to a
model — so it runs offline against any finished run.

    # after a run prints its `ledger db : <path>`
    python standup-app/report.py --db /tmp/chorus-standup-XXXX/company.db
    python standup-app/report.py --db <path> --out report.md        # write Markdown to a file

``--team`` and ``--org`` runs auto-write ``report.md`` next to the ledger; this script lets you
regenerate it (or point it at any other run's ``company.db``).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from chorus.ledger import SqliteLedger, TaskStatus
from chorus.ledger._models import Task
from chorus.workforce._models import Employee

# Terminal task states (a leaf that reached one of these has "landed" or been closed).
_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})

# Per-status Mermaid class + a plain glyph for the text tree.
_STATUS_CLASS = {
    "done": "done",
    "in_progress": "active",
    "in_review": "active",
    "todo": "active",
    "blocked": "blocked",
    "rejected": "blocked",
    "cancelled": "blocked",
    "backlog": "idle",
}
_STATUS_GLYPH = {
    "done": "✓",
    "in_progress": "•",
    "in_review": "•",
    "todo": "•",
    "blocked": "✗",
    "rejected": "✗",
    "cancelled": "✗",
    "backlog": "·",
}


# ── ledger reads ────────────────────────────────────────────────────────────────────────────────

def _latest_beat(ledger: SqliteLedger, task_id: str) -> str:
    runs = ledger.runs.for_task(task_id)
    return runs[-1].status.value if runs else "-"


def _employee_label(emp: Employee | None, fallback: str | None) -> str:
    if emp is not None:
        return f"{emp.name} ({emp.role})"
    return fallback or "—"


# ── Mermaid helpers ─────────────────────────────────────────────────────────────────────────────

def _node_id(prefix: str, raw: str) -> str:
    """A Mermaid-safe node id: alnum + underscore only."""
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw)
    return f"{prefix}_{safe}"


def _mermaid_label(text: str, *, limit: int = 46) -> str:
    """Escape a label for a Mermaid ["..."] node (drop quotes/newlines, clip length)."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        flat = flat[: limit - 1] + "…"
    return flat.replace('"', "'").replace("[", "(").replace("]", ")")


# ── sections ──────────────────────────────────────────────────────────────────────────────────────

def _org_chart(employees: list[Employee]) -> str:
    by_id = {e.id: e for e in employees}
    lines = ["```mermaid", "graph TD"]
    for emp in employees:
        nid = _node_id("e", emp.id)
        lines.append(f'    {nid}["{_mermaid_label(emp.name)}<br/><i>{emp.role}</i>"]')
    for emp in employees:
        if emp.reports_to and emp.reports_to in by_id:
            lines.append(f"    {_node_id('e', emp.reports_to)} --> {_node_id('e', emp.id)}")
    # tint managers (anyone who is reported to) vs leaves
    manager_ids = {e.reports_to for e in employees if e.reports_to}
    lines.append("    classDef mgr fill:#1f6feb,stroke:#0b3d91,color:#fff;")
    lines.append("    classDef leaf fill:#2d333b,stroke:#444c56,color:#adbac7;")
    for emp in employees:
        cls = "mgr" if emp.id in manager_ids else "leaf"
        lines.append(f"    class {_node_id('e', emp.id)} {cls};")
    lines.append("```")
    return "\n".join(lines)


def _roster_table(employees: list[Employee]) -> str:
    rows = ["| id | name | role | reports to |", "| --- | --- | --- | --- |"]
    for emp in sorted(employees, key=lambda e: (e.reports_to or "", e.id)):
        rows.append(f"| `{emp.id}` | {emp.name} | {emp.role} | {emp.reports_to or '—'} |")
    return "\n".join(rows)


def _decomposition_graph(
    tasks: list[Task], children_of: dict[str | None, list[Task]], by_id: dict[str, Employee]
) -> str:
    lines = ["```mermaid", "graph TD"]
    for task in tasks:
        nid = _node_id("t", task.id)
        emp = by_id.get(task.assignee_employee_id or "")
        who = emp.name if emp is not None else (task.assignee_employee_id or "—")
        role = f" · {emp.role}" if emp is not None else ""
        label = _mermaid_label(task.intent or task.id)
        lines.append(f'    {nid}["{label}<br/><b>{who}{role}</b><br/>[{task.status.value}]"]')
    for parent_id, kids in children_of.items():
        if parent_id is None:
            continue
        for kid in kids:
            lines.append(f"    {_node_id('t', parent_id)} --> {_node_id('t', kid.id)}")
    lines.append("    classDef done fill:#238636,stroke:#1a6e2e,color:#fff;")
    lines.append("    classDef active fill:#9e6a03,stroke:#7a5200,color:#fff;")
    lines.append("    classDef blocked fill:#b62324,stroke:#8a1b1c,color:#fff;")
    lines.append("    classDef idle fill:#2d333b,stroke:#444c56,color:#adbac7;")
    for task in tasks:
        cls = _STATUS_CLASS.get(task.status.value, "idle")
        lines.append(f"    class {_node_id('t', task.id)} {cls};")
    lines.append("```")
    return "\n".join(lines)


def _text_tree(
    ledger: SqliteLedger,
    children_of: dict[str | None, list[Task]],
    by_id: dict[str, Employee],
) -> str:
    out: list[str] = ["```"]

    def walk(task: Task, indent: int) -> None:
        glyph = _STATUS_GLYPH.get(task.status.value, "·")
        emp = by_id.get(task.assignee_employee_id or "")
        who = _employee_label(emp, task.assignee_employee_id)
        beat = _latest_beat(ledger, task.id)
        pad = "  " * indent
        intent = " ".join((task.intent or "").split())[:60]
        out.append(f"{pad}{glyph} [{task.status.value:<11}] {who:<18} beat={beat:<9} {intent}")
        for kid in children_of.get(task.id, []):
            walk(kid, indent + 1)

    for root in children_of.get(None, []):
        walk(root, 0)
    out.append("```")
    return "\n".join(out)


def _task_table(
    ledger: SqliteLedger, tasks: list[Task], by_id: dict[str, Employee]
) -> str:
    rows = [
        "| task | depth | assignee (role) | status | latest beat | intent |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for task in sorted(tasks, key=lambda t: (t.depth, t.id)):
        emp = by_id.get(task.assignee_employee_id or "")
        who = _employee_label(emp, task.assignee_employee_id)
        intent = " ".join((task.intent or "").split())[:70]
        rows.append(
            f"| `{task.id}` | {task.depth} | {who} | {task.status.value} | "
            f"{_latest_beat(ledger, task.id)} | {intent} |"
        )
    return "\n".join(rows)


def _rollup(employees: list[Employee], tasks: list[Task]) -> str:
    role_counts = Counter(e.role for e in employees)
    status_counts = Counter(t.status.value for t in tasks)
    manager_ids = {e.reports_to for e in employees if e.reports_to}
    leaves = sum(1 for e in employees if e.id not in manager_ids)
    delegated = sum(1 for t in tasks if t.parent_id is not None)
    landed = sum(1 for t in tasks if t.status in _TERMINAL)
    max_depth = max((t.depth for t in tasks), default=0)
    lines = [
        f"- **employees:** {len(employees)}  "
        + " · ".join(f"{n}×{r}" for r, n in sorted(role_counts.items())),
        f"- **org tiers:** {len(manager_ids)} manager(s) over {leaves} leaf employee(s)",
        f"- **tasks:** {len(tasks)} total, max delegation depth {max_depth}, "
        f"{delegated} delegated (child) task(s)",
        "- **task status:** " + " · ".join(f"{n} {s}" for s, n in sorted(status_counts.items())),
        f"- **terminal tasks:** {landed}/{len(tasks)}",
    ]
    return "\n".join(lines)


# ── top level ─────────────────────────────────────────────────────────────────────────────────────

def build_report(db_path: str) -> str:
    """Read the ledger at ``db_path`` and return the full Markdown report."""
    ledger = SqliteLedger.open(db_path)
    try:
        employees = ledger.employees.list()
        tasks = ledger.tasks.all()
    finally:
        ledger.close()

    by_emp = {e.id: e for e in employees}
    children_of: dict[str | None, list[Task]] = defaultdict(list)
    for task in sorted(tasks, key=lambda t: (t.depth, t.id)):
        children_of[task.parent_id].append(task)

    # Re-open for per-task run lookups in the section builders (cheap; same file).
    ledger = SqliteLedger.open(db_path)
    try:
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        parts = [
            "# chorus run — decomposition report",
            f"_generated {when} from `{db_path}`_",
            "",
            "## Rollup",
            _rollup(employees, tasks),
            "",
            "## Org chart",
            _org_chart(employees) if employees else "_no employees_",
            "",
            "### Roster",
            _roster_table(employees) if employees else "_no employees_",
            "",
            "## Task decomposition tree",
            _decomposition_graph(tasks, children_of, by_emp) if tasks else "_no tasks_",
            "",
            "### Decomposition (indented)",
            _text_tree(ledger, children_of, by_emp) if tasks else "_no tasks_",
            "",
            "## Tasks",
            _task_table(ledger, tasks, by_emp) if tasks else "_no tasks_",
            "",
        ]
    finally:
        ledger.close()
    return "\n".join(parts)


def write_report(db_path: str, *, out_path: str | None = None) -> str:
    """Build the report and (optionally) write it to ``out_path``; returns the Markdown."""
    report = build_report(db_path)
    if out_path is not None:
        Path(out_path).write_text(report, encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Draw a chorus run's org chart + decomposition tree.")
    parser.add_argument("--db", required=True, help="path to the run's company.db ledger")
    parser.add_argument("--out", default=None, help="write the Markdown report to this file")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"ledger not found: {args.db}", file=sys.stderr)
        return 2

    report = write_report(args.db, out_path=args.out)
    if args.out:
        print(f"report written → {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
