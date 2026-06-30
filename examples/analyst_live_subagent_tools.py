"""Live Iteration-3 task — a substantial two-table investigation the Analyst can delegate.

The warehouse has `sales` and `targets`; answering needs a join, per-(region,quarter) attainment, a
best-average ranking, a quarter comparison, a correlation, and a chart. The task SUGGESTS (does not
mandate) delegating data prep to the `data` subagent and modelling to `modeling` — those specialists
now carry the analysis tools (warehouse_query / notebook_run / chart_render), so a spawned subagent
can pull from the warehouse and compute. Passes the role DoD.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_subagent_tools.py
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
    "The SQLite warehouse `warehouse.db` has two tables: `sales(region, quarter, revenue)` and "
    "`targets(region, quarter, target)`. Investigate and report, with exact numbers: (1) the "
    "attainment (revenue/target*100) for every (region, quarter); (2) the region with the highest "
    "average attainment across quarters; (3) the quarter in which total revenue most exceeded total "
    "target (across all regions); (4) the Pearson correlation between revenue and target across all "
    "(region, quarter) rows. Render a chart of attainment by quarter for each region. Begin by "
    "delegating the SQL data preparation — the join and the per-(region, quarter) attainment table — to "
    "your `data` subagent with spawn_subagent; then do the modelling, correlation, and charting "
    "yourself and write the findings."
)

_SALES = [
    ("A", "Q1", 1000), ("A", "Q2", 1200), ("A", "Q3", 1500),
    ("B", "Q1", 800), ("B", "Q2", 900), ("B", "Q3", 1100),
    ("C", "Q1", 600), ("C", "Q2", 700), ("C", "Q3", 650),
]
_TARGETS = [
    ("A", "Q1", 900), ("A", "Q2", 1100), ("A", "Q3", 1300),
    ("B", "Q1", 850), ("B", "Q2", 950), ("B", "Q3", 1000),
    ("C", "Q1", 700), ("C", "Q2", 700), ("C", "Q3", 800),
]


def _seed(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales (region TEXT, quarter TEXT, revenue INTEGER)")
    conn.execute("CREATE TABLE targets (region TEXT, quarter TEXT, target INTEGER)")
    conn.executemany("INSERT INTO sales VALUES (?, ?, ?)", _SALES)
    conn.executemany("INSERT INTO targets VALUES (?, ?, ?)", _TARGETS)
    conn.commit()
    conn.close()


def _short(value: object, n: int = 240) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _print_event(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_TOOL_USE:
        tool = p.get("tool")
        marker = "  [SUBAGENT ->]" if tool == "spawn_subagent" else "  [tool ->]"
        print(f"{marker} {tool}  input={_short(p.get('input'))}")
    elif ev.kind is EventKind.RUN_TOOL_RESULT:
        tool = p.get("tool")
        flag = " (ERROR)" if p.get("is_error") else ""
        marker = "  [SUBAGENT <-]" if tool == "spawn_subagent" else "  [tool <-]"
        print(f"{marker} {tool}{flag}  {_short(p.get('content_preview'))}")
    elif ev.kind is EventKind.RUN_DONE:
        print("== beat done ==")


async def main() -> int:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    base = os.environ.get("AZURE_OPENAI_BASE_URL")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (key and base and dep):
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=dep, company_id="analyst-subagent-tools",
        roles=roles, timeout_s=900.0,
    )
    mat = factory.materialize(Employee(id="vera", name="Vera", role="analyst"))
    _seed(mat.working_dir / "warehouse.db")

    print(f"worktree  : {mat.working_dir}")
    print(f"subagents : {[(s.name, s.tools) for s in mat.config.subagents]}")
    print(f"intent    : {_INTENT}\n")

    verifier = analyst_plugin().dod_generator(_INTENT)
    outcome = await mat.runner.run_task(
        task_id="subtools-1", intent=_INTENT, run_id="run-subtools-1",
        verification=verifier.verification_steps(), rubric=verifier.rubric(), observer=_print_event,
    )

    print(f"\npassed   = {outcome.passed}")
    print(f"summary  = {outcome.summary}")
    print(f"charts   = {[p.name for p in mat.working_dir.glob('*.png')]}")
    findings = mat.working_dir / "findings.md"
    if findings.is_file():
        print(f"\n----- findings.md -----\n{findings.read_text(encoding='utf-8')}")
    else:
        print("\n(no findings.md written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
