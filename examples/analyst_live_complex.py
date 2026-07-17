"""Live complex task — one real Analyst beat on a multi-dimensional dataset.

Same path as the baseline (materialize via :class:`EmployeeHarnessFactory`, run ONE beat, print
every tool call), but the task needs real data work — per-(channel,month) churn, lowest-average
channel, worst cell, a Pearson correlation, and per-channel trend — so the Analyst must actually use
``pandas``/``numpy`` rather than eyeball five rows.

The Analyst's ``run_command`` subprocess inherits THIS process's environment, and ``python`` resolves
via PATH. We prepend the running interpreter's directory (the chorus venv, where pandas/numpy are
installed) so the Analyst's ``python analysis.py`` resolves to an interpreter that has the stack.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_complex.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

# Windows consoles default to cp1252; force UTF-8 so printing a tool arrow can't raise mid-beat.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# Make the Analyst's ``python`` resolve to THIS interpreter (the chorus venv with pandas/numpy):
# bash passes no env, so the sandbox subprocess inherits os.environ; prepend our Scripts/bin dir.
_INTERP_DIR = str(Path(sys.executable).parent)
os.environ["PATH"] = _INTERP_DIR + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import EmployeeHarnessFactory

_INTENT = (
    "A CSV named events.csv is in your working directory with columns "
    "month,channel,signups,churned,revenue (multiple acquisition channels across several months). "
    "(1) Compute the churn rate (churned / signups * 100) for every (channel, month) row. "
    "(2) Identify the acquisition channel with the LOWEST average churn rate across the period. "
    "(3) Identify the single worst (channel, month) cell by churn rate. "
    "(4) Compute the Pearson correlation between revenue and churn rate across all rows. "
    "(5) For each channel, state whether its churn rate is trending up or down across the months. "
    "Report the exact numbers you compute."
)

_CSV = (
    "month,channel,signups,churned,revenue\n"
    "Jan,organic,1000,30,5000\n"
    "Feb,organic,1100,35,5400\n"
    "Mar,organic,1200,48,5800\n"
    "Apr,organic,1300,52,6200\n"
    "Jan,paid,800,64,3000\n"
    "Feb,paid,850,77,3100\n"
    "Mar,paid,900,99,3200\n"
    "Apr,paid,950,124,3300\n"
    "Jan,referral,400,8,1800\n"
    "Feb,referral,450,9,2000\n"
    "Mar,referral,500,12,2200\n"
    "Apr,referral,550,14,2400\n"
)


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
        company_id="analyst-complex",
        roles=roles,
        timeout_s=600.0,
    )
    analyst = Employee(id="vera", name="Vera", role="analyst")
    mat = factory.materialize(analyst)
    (mat.working_dir / "events.csv").write_text(_CSV, encoding="utf-8")

    print(f"worktree : {mat.working_dir}")
    print(f"python   : {_INTERP_DIR}")
    print(f"tools    : {mat.config.tools}")
    print(
        f"sandbox  : {mat.config.sandbox}  max_turns={mat.config.max_turns}  max_sprints={mat.config.max_sprints}"
    )
    print(f"intent   : {_INTENT}\n")

    outcome = await mat.runner.run_task(
        task_id="complex-1",
        intent=_INTENT,
        run_id="run-complex-1",
        observer=_print_event,
    )

    print(f"\npassed   = {outcome.passed}")
    print(f"summary  = {outcome.summary}")
    findings = mat.working_dir / "findings.md"
    if findings.is_file():
        print(f"\n----- findings.md -----\n{findings.read_text(encoding='utf-8')}")
    else:
        print("\n(no findings.md written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
