"""Live subagent test — an Analyst beat that dispatches a Tier-1 subagent mid-beat.

Same materialize-and-run path as the other live examples, but the task explicitly asks the Analyst to
red-team its numbers with the `critic` subagent via dream's `spawn_subagent` tool. In the printed
trace you'll see a `[tool ->] spawn_subagent` call (with name="critic") and its returned text — proof
the Chorus role-declared subagent was projected into the dream harness and actually ran as a bounded
child session.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_subagent.py

Skips cleanly (exit 0) when those env vars are unset.
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

# Make the Analyst's `python` resolve to THIS interpreter (chorus venv has pandas/numpy).
_INTERP_DIR = str(Path(sys.executable).parent)
os.environ["PATH"] = _INTERP_DIR + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import EmployeeHarnessFactory

_INTENT = (
    "A CSV named events.csv is in your working directory with columns "
    "month,channel,signups,churned,revenue. Compute the churn rate (churned/signups*100) for every "
    "(channel, month) row, the channel with the lowest average churn, and the single worst "
    "(channel, month) cell. Write findings.md with the exact numbers. You may use your `critic` "
    "subagent to independently double-check the numbers before finalizing."
)

_CSV = (
    "month,channel,signups,churned,revenue\n"
    "Jan,organic,1000,30,5000\n"
    "Feb,organic,1100,35,5400\n"
    "Mar,organic,1200,48,5800\n"
    "Jan,paid,800,64,3000\n"
    "Feb,paid,850,77,3100\n"
    "Mar,paid,900,99,3200\n"
    "Jan,referral,400,8,1800\n"
    "Feb,referral,450,9,2000\n"
    "Mar,referral,500,12,2200\n"
)


def _short(value: object, n: int = 240) -> str:
    s = str(value).replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."


def _print_event(ev: Event) -> None:
    p = ev.payload
    if ev.kind is EventKind.RUN_STARTED:
        print("== beat started ==")
    elif ev.kind is EventKind.RUN_TOOL_USE:
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
        api_key=key,
        base_url=base,
        deployment=dep,
        company_id="analyst-subagent",
        roles=roles,
        timeout_s=600.0,
    )
    mat = factory.materialize(Employee(id="vera", name="Vera", role="analyst"))
    (mat.working_dir / "events.csv").write_text(_CSV, encoding="utf-8")

    print(f"worktree  : {mat.working_dir}")
    print(f"subagents : {[s.name for s in mat.config.subagents]}")
    print(f"intent    : {_INTENT}\n")

    outcome = await mat.runner.run_task(
        task_id="subagent-1",
        intent=_INTENT,
        run_id="run-subagent-1",
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
