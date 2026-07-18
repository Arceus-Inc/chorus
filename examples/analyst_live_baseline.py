"""Live baseline — one real Analyst beat through the configured employee harness.

Materializes the Analyst via :class:`EmployeeHarnessFactory` (its REAL manifest: tools, sandbox,
brief), seeds a tiny CSV in its worktree, runs ONE beat against Azure, and prints every tool call +
reasoning so we can see exactly what the Analyst does today. This is the Phase-1 baseline.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_baseline.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Windows consoles default to cp1252; force UTF-8 so printing a tool arrow can't
# raise mid-beat (a raise in the observer aborts run_task as a plan-phase error).
for _stream in (sys.stdout, sys.stderr):
    with __import__("contextlib").suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import EmployeeHarnessFactory

_INTENT = (
    "A CSV file named churn.csv is in your working directory with columns month,signups,churned. "
    "Compute the monthly churn rate (churned / signups) for each month as a percentage, identify the "
    "single worst month, and state whether churn is trending up or down across the period."
)

_CSV = "month,signups,churned\nJan,1000,40\nFeb,1100,55\nMar,1200,84\nApr,1250,100\nMay,1300,143\n"


def _short(value: object, n: int = 220) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _print_event(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_STARTED:
        print("== beat started ==")
    elif ev.kind is EventKind.RUN_TOOL_USE:
        print(f"  [tool ->] {p.get('tool')}  input={_short(p.get('input'))}")
    elif ev.kind is EventKind.RUN_TOOL_RESULT:
        flag = " (ERROR)" if p.get("is_error") else ""
        print(f"  [tool <-] {p.get('tool')}{flag}  {_short(p.get('content_preview'))}")
    elif ev.kind is EventKind.RUN_TEXT:
        text = str(p.get("text", "")).strip()
        if text:
            print(f"  [think]   {_short(text, 400)}")
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
        company_id="analyst-baseline",
        roles=roles,
        timeout_s=300.0,
    )
    analyst = Employee(id="vera", name="Vera", role="analyst")
    mat = factory.materialize(analyst)

    # Seed the data file in the Analyst's own branch-isolated worktree.
    (mat.working_dir / "churn.csv").write_text(_CSV, encoding="utf-8")

    print(f"worktree : {mat.working_dir}")
    print(f"tools    : {mat.config.tools}")
    print(
        f"sandbox  : {mat.config.sandbox}  max_turns={mat.config.max_turns}  max_sprints={mat.config.max_sprints}"
    )
    print(f"intent   : {_INTENT}\n")

    outcome = await mat.runner.run_task(
        task_id="baseline-1",
        intent=_INTENT,
        run_id="run-baseline-1",
        observer=_print_event,
    )

    print(f"\npassed   = {outcome.passed}")
    print(f"summary  = {outcome.summary}")
    print(f"outcome  = {outcome.outcome}")
    findings = mat.working_dir / "findings.md"
    if findings.is_file():
        print(f"\n----- findings.md -----\n{findings.read_text(encoding='utf-8')}")
    else:
        print("\n(no findings.md written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
