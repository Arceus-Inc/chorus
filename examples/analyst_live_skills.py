"""Live Iteration-2 task — messy data that rewards the Analyst's skills (EDA + trend).

A deliberately messy CSV (a missing value, a zero-denominator row, an exact duplicate) where naive
computation gives a wrong answer. The Analyst's authored playbooks (exploratory-data-analysis,
trend-and-correlation) are offered via the `skill` tool; a careful analyst profiles first, handles the
data-quality issues, then quantifies the trend. Passes the role DoD.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_skills.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
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
    "A CSV `weekly_activation.csv` is in your working directory with columns week, signups, activated. "
    "The data has quality issues you must handle correctly. Compute the weekly activation rate "
    "(activated / signups * 100) for each week where it is defined, decide whether activation is "
    "trending up or down over the period and by how much (a slope), and state the activation rate of "
    "the best and worst valid weeks. Report exact numbers and note explicitly how you handled the "
    "data-quality issues."
)

# week, signups, activated — a missing signups (w3), a zero-denominator (w5), and an exact duplicate (w7).
_CSV = (
    "week,signups,activated\n"
    "w1,1000,200\n"
    "w2,1100,250\n"
    "w3,,280\n"
    "w4,1200,300\n"
    "w5,0,0\n"
    "w6,1300,400\n"
    "w7,1300,420\n"
    "w7,1300,420\n"
    "w8,1400,480\n"
)


def _short(value: object, n: int = 240) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _print_event(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_TOOL_USE:
        tool = p.get("tool")
        marker = "  [SKILL ->]" if tool == "skill" else "  [tool ->]"
        print(f"{marker} {tool}  input={_short(p.get('input'))}")
    elif ev.kind is EventKind.RUN_TOOL_RESULT:
        tool = p.get("tool")
        flag = " (ERROR)" if p.get("is_error") else ""
        marker = "  [SKILL <-]" if tool == "skill" else "  [tool <-]"
        print(f"{marker} {tool}{flag}  {_short(p.get('content_preview'))}")
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
        company_id="analyst-skills",
        roles=roles,
        timeout_s=600.0,
    )
    mat = factory.materialize(Employee(id="vera", name="Vera", role="analyst"))
    (mat.working_dir / "weekly_activation.csv").write_text(_CSV, encoding="utf-8")

    print(f"worktree : {mat.working_dir}")
    print(f"skills   : {mat.config.skills}")
    print(f"intent   : {_INTENT}\n")

    verifier = analyst_plugin().dod_generator(_INTENT)
    outcome = await mat.runner.run_task(
        task_id="skills-1",
        intent=_INTENT,
        run_id="run-skills-1",
        verification=verifier.verification_steps(),
        rubric=verifier.rubric(),
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
