"""Live capstone — a hard Analyst investigation through the REAL kernel, end to end.

Not a manual run_task call: the chorus Scheduler dispatches the beat, creates the Analyst's
AgentReview DoD at intake, enforces it in-beat, and lands the `finding` artifact on pass — the whole
loop on its own. The task is a hard two-table warehouse investigation (join, per-region margin, best
region, top-profit quarter, a correlation, a chart). The Analyst has its full kit: analysis tools,
authored skills, and a subagent swarm.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_scheduler_e2e.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_harness import EmployeeHarnessFactory

_EMPLOYEE = "vera"
_TASK = "capstone"
_TERMINAL = (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.REJECTED)
_TIMEOUT_TICKS = 360

_INTENT = (
    "The SQLite warehouse `warehouse.db` has two tables: `sales(region, quarter, revenue, units)` and "
    "`costs(region, quarter, cost)`. Investigate and report, with exact numbers: (1) the profit margin "
    "((revenue - cost) / revenue * 100) for every (region, quarter); (2) the region with the highest "
    "average profit margin across quarters; (3) the quarter with the highest total profit "
    "(revenue - cost summed across regions); (4) the Pearson correlation between units and profit "
    "across all (region, quarter) rows. Render a chart of profit margin by quarter for each region. "
    "Write findings.md with the exact numbers."
)

_SALES = [
    ("A", "Q1", 1000, 100), ("A", "Q2", 1200, 110), ("A", "Q3", 1500, 130),
    ("B", "Q1", 800, 90), ("B", "Q2", 900, 95), ("B", "Q3", 1100, 105),
    ("C", "Q1", 600, 70), ("C", "Q2", 700, 72), ("C", "Q3", 650, 68),
]
_COSTS = [
    ("A", "Q1", 700), ("A", "Q2", 800), ("A", "Q3", 900),
    ("B", "Q1", 650), ("B", "Q2", 700), ("B", "Q3", 800),
    ("C", "Q1", 500), ("C", "Q2", 520), ("C", "Q3", 560),
]


def _seed(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (region TEXT, quarter TEXT, revenue INTEGER, units INTEGER)")
    conn.execute("CREATE TABLE costs (region TEXT, quarter TEXT, cost INTEGER)")
    conn.executemany("INSERT INTO sales VALUES (?, ?, ?, ?)", _SALES)
    conn.executemany("INSERT INTO costs VALUES (?, ?, ?)", _COSTS)
    conn.commit()
    conn.close()


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    ledger = SqliteLedger.open(":memory:")
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=dep, company_id="analyst-capstone",
        roles=registry, ledger=ledger, timeout_s=900.0,
    )
    # Pre-materialize to create the worktree, then seed the warehouse into it (path-based continuity:
    # the kernel's beat reuses the same worktree).
    mat = factory.materialize(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))
    _seed(mat.working_dir / "warehouse.db")

    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=factory,  # the factory implements BeatRunnerFor (runner_for per employee)
        landers=factory.landers,
        roles=registry,  # the kernel creates the Analyst's AgentReview DoD at intake
        max_concurrent_runs=1,
    )

    ledger.employees.create(Employee(id=_EMPLOYEE, name="Vera", role="analyst"))
    ledger.tasks.submit(Task(id=_TASK, intent=_INTENT))
    assign_task(ledger, _TASK, _EMPLOYEE)

    print(f"worktree : {mat.working_dir}")
    print(f"running the kernel — task {_TASK!r} flows through wake -> beat -> DoD -> land\n")
    last = ""
    loop = asyncio.create_task(scheduler.run())
    try:
        for _ in range(_TIMEOUT_TICKS):
            await asyncio.sleep(1)
            task = ledger.tasks.get(_TASK)
            assert task is not None
            if task.status.value != last:
                last = task.status.value
                print(f"  task {_TASK}: {last}")
            if task.status in _TERMINAL:
                break
    finally:
        scheduler.stop()
        await loop

    runs = ledger.runs.for_task(_TASK)
    if runs:
        print(f"\nrun     : status={runs[-1].status.value} outcome={runs[-1].outcome}")
    dod = ledger.dod.get_for_task(_TASK)
    if dod is not None:
        print(f"dod     : status={dod.status.value} verdict={dod.verdict}")
    with contextlib.suppress(Exception):
        arts = ledger.artifacts.list_for_task(_TASK)
        print(f"artifacts: {[a.type.value for a in arts]}")
    findings = mat.working_dir / "findings.md"
    if findings.is_file():
        print(f"\n----- findings.md -----\n{findings.read_text(encoding='utf-8')}")
    ledger.close()
    print(f"\nfinal: {last}")
    return 0 if last == TaskStatus.DONE.value else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
