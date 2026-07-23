"""Live Iteration-1 task — the Analyst investigates a local SQL warehouse end to end.

Seeds a SQLite `warehouse.db` (a `sales` table) in the Analyst's worktree, then asks a medium-difficulty
question that requires SQL aggregation, a notebook computation (growth + correlation), and a rendered
chart. In the trace you'll see warehouse_query / notebook_run / chart_render calls — the Analyst's new
instruments — and the beat should pass with a findings.md plus a chart PNG.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_warehouse.py
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

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_employee.analyst import analyst_plugin
from chorus_harness import EmployeeHarnessFactory

_INTENT = (
    "A SQLite data warehouse `warehouse.db` is in your working directory with a `sales` table "
    "(columns: region, month, product, units, revenue). Investigate and report, with exact numbers: "
    "(1) the region with the highest total revenue; (2) the month with the largest month-over-month "
    "increase in total revenue across all regions; (3) the Pearson correlation between units and "
    "revenue across all rows. Then render a line chart of total monthly revenue per region to a PNG and "
    "name it in your findings. Use the SQL warehouse to aggregate and the notebook to compute."
)

# (region, month, product, units, revenue)
_ROWS = [
    ("West", "Jan", "A", 100, 1000),
    ("West", "Jan", "B", 50, 750),
    ("West", "Feb", "A", 120, 1200),
    ("West", "Feb", "B", 60, 900),
    ("West", "Mar", "A", 140, 1400),
    ("West", "Mar", "B", 70, 1050),
    ("West", "Apr", "A", 160, 1600),
    ("West", "Apr", "B", 80, 1200),
    ("East", "Jan", "A", 80, 800),
    ("East", "Jan", "B", 40, 600),
    ("East", "Feb", "A", 85, 850),
    ("East", "Feb", "B", 42, 630),
    ("East", "Mar", "A", 90, 900),
    ("East", "Mar", "B", 45, 675),
    ("East", "Apr", "A", 95, 950),
    ("East", "Apr", "B", 47, 705),
    ("North", "Jan", "A", 30, 300),
    ("North", "Jan", "B", 20, 300),
    ("North", "Feb", "A", 45, 450),
    ("North", "Feb", "B", 30, 450),
    ("North", "Mar", "A", 70, 700),
    ("North", "Mar", "B", 50, 750),
    ("North", "Apr", "A", 110, 1100),
    ("North", "Apr", "B", 80, 1200),
]


def _seed_warehouse(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sales (region TEXT, month TEXT, product TEXT, units INTEGER, revenue INTEGER)"
    )
    conn.executemany("INSERT INTO sales VALUES (?, ?, ?, ?, ?)", _ROWS)
    conn.commit()
    conn.close()


def _short(value: object, n: int = 240) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _print_event(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_TOOL_USE:
        print(f"  [tool ->] {p.get('tool')}  input={_short(p.get('input'))}")
    elif ev.kind is EventKind.RUN_TOOL_RESULT:
        flag = " (ERROR)" if p.get("is_error") else ""
        print(f"  [tool <-] {p.get('tool')}{flag}  {_short(p.get('content_preview'))}")
    elif ev.kind is EventKind.RUN_DONE:
        print("== beat done ==")


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print(
            "skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT"
        )
        return 0

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key,
        base_url=base,
        deployment=dep,
        company_id="analyst-warehouse",
        roles=roles,
        timeout_s=600.0,
    )
    mat = factory.materialize(Employee(id="vera", name="Vera", role="analyst"))
    _seed_warehouse(mat.working_dir / "warehouse.db")

    print(f"worktree : {mat.working_dir}")
    print(f"tools    : {mat.config.tools}")
    print(f"intent   : {_INTENT}\n")

    # Exercise the Analyst's real DoD (what the scheduler passes): the evaluator judges findings.md
    # against the role's agent-review rubric.
    verifier = analyst_plugin().dod_generator(_INTENT)
    outcome = await mat.runner.run_task(
        task_id="warehouse-1",
        intent=_INTENT,
        run_id="run-warehouse-1",
        verification=verifier.verification_steps(),
        rubric=verifier.rubric(),
        observer=_print_event,
    )

    print(f"\npassed   = {outcome.passed}")
    print(f"summary  = {outcome.summary}")
    pngs = list(mat.working_dir.glob("*.png"))
    print(f"charts   = {[p.name for p in pngs]}")
    findings = mat.working_dir / "findings.md"
    if findings.is_file():
        print(f"\n----- findings.md -----\n{findings.read_text(encoding='utf-8')}")
    else:
        print("\n(no findings.md written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
