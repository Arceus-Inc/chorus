"""Live baseline — one real CEO beat through the configured employee harness.

Materializes the CEO via :class:`EmployeeHarnessFactory` (its REAL manifest: executive toolset, skills,
sandbox, brief), seeds a company-state file in its worktree, runs ONE governance beat against Azure, and
prints every tool call + reasoning so we can see exactly what the CEO does. Its deliverable is
``directive.md``, judged by the CEO's AgentReview DoD.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/ceo_live_baseline.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Windows consoles default to cp1252; force UTF-8 so printing a tool arrow can't raise mid-beat.
for _stream in (sys.stdout, sys.stderr):
    with __import__("contextlib").suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import EmployeeHarnessFactory

_INTENT = (
    "Review the company's current direction in `company-state.md` (read it first). Decide where to "
    "concentrate next quarter, adjudicate the two open proposals (approve or reject EACH with your "
    "reasoning), and say concretely what to do about any blocked or stalled goal. Write your directive."
)

_COMPANY_STATE = """# Company state — this quarter

Single priority: **profitable growth** (not top-line vanity).

## Decision: Grow next-quarter profit using the sales warehouse
Goals:
- [goal_a1] Build the profit-by-region-and-quarter dataset — score 0.90, priority HIGH, health: BLOCKED (its Definition of Done has failed twice). It is the upstream dependency for goal_a3 and goal_a4.
- [goal_a2] Quantify historical profit drivers and variability — score 0.80, priority HIGH, health: on_track, status: DONE.
- [goal_a3] Rank the top profit-growth opportunities by region — score 0.70, priority MEDIUM, health: unknown, status: active (waiting on goal_a1).
- [goal_a4] Produce an executive-ready recommendation memo — score 0.60, priority MEDIUM, health: unknown, status: active (waiting on goal_a1).

## Open proposals (awaiting a decision)
- [prop_strong] "Concentrate next-quarter sales investment on Region A (highest profit efficiency)" — confidence 0.86, evidence: 3 independent sources (profit-per-cost by region, growth trend, sensitivity check).
- [prop_weak] "Rebrand the company logo and website next quarter" — confidence 0.50, evidence: 1 source (a team member felt the brand looks dated).

## Recent outcomes
- goal_a1 has failed its Definition of Done twice; the analyst could not satisfy the statistical bar from the available Q1-Q3 data alone.
- goal_a2 landed clean and is done.
"""


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
        company_id="ceo-baseline",
        roles=roles,
        timeout_s=600.0,
    )
    ceo = Employee(id="casey", name="Casey (CEO)", role="ceo")
    mat = factory.materialize(ceo)

    (mat.working_dir / "company-state.md").write_text(_COMPANY_STATE, encoding="utf-8")

    print(f"worktree : {mat.working_dir}")
    print(f"tools    : {mat.config.tools}")
    print(
        f"sandbox  : {mat.config.sandbox}  max_turns={mat.config.max_turns}  max_sprints={mat.config.max_sprints}"
    )
    print(f"intent   : {_INTENT}\n")

    outcome = await mat.runner.run_task(
        task_id="ceo-baseline-1",
        intent=_INTENT,
        run_id="run-ceo-baseline-1",
        observer=_print_event,
    )

    print(f"\npassed   = {outcome.passed}")
    print(f"summary  = {outcome.summary}")
    print(f"outcome  = {outcome.outcome}")
    directive = mat.working_dir / "directive.md"
    if directive.is_file():
        print(f"\n----- directive.md -----\n{directive.read_text(encoding='utf-8')}")
    else:
        print("\n(no directive.md written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
