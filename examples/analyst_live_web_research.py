"""Live web-research task — one real Analyst beat that must use the web, gated by the action-class DoD.

This exercises the two things added on ``analyst-integrations``:

- **dream's built-in ``web_search``/``web_extract``** driven with a real Tavily key (``TAVILY_API_KEY``),
  so the whole external-research pipeline runs end-to-end, not a mock;
- **the action-class-aware DoD** (:func:`chorus_employee.analyst.analyst_dod`): the intent below carries
  no predict/recommend cues, so it classifies as ``FINDINGS`` and the beat is gated by an AgentReview
  the evaluator model judges against the committed ``findings.md``.

The question is deliberately multi-part and current, so the Analyst can't answer from memory — it has
to search, read a source in full, and cite the exact URL behind every claim.

    TAVILY_API_KEY=... AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_web_research.py

Skips cleanly (exit 0) when the model env vars are unset.
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

os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_employee.analyst import analyst_dod, classify_action
from chorus_harness import EmployeeHarnessFactory

_INTENT = (
    "You are compiling a short technical brief on the current open-source vector-database landscape. "
    "You have no local data on this, so you will need to research it on the web. Answer each of the "
    "following, and for EVERY factual claim cite the source URL it came from:\n"
    "(1) Name three widely-used open-source vector databases.\n"
    "(2) For each of the three, state its primary implementation language.\n"
    "(3) Of the three, which has the most GitHub stars? Give the approximate star count and the URL "
    "you took it from.\n"
    "(4) In one or two sentences each, summarise one distinctive feature of each of the three.\n"
    "Write `findings.md` with a clearly labelled section per question. Every name and number must "
    "carry a source URL — a factual claim with no source is not acceptable."
)


def _short(value: object, n: int = 240) -> str:
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
    if not (os.environ.get("TAVILY_API_KEY") or os.environ.get("DREAM_TAVILY_API_KEY")):
        print("skipping: set TAVILY_API_KEY (or DREAM_TAVILY_API_KEY) for the web tools")
        return 0

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key,
        base_url=base,
        deployment=dep,
        company_id="analyst-web-research",
        roles=roles,
        timeout_s=600.0,
    )
    mat = factory.materialize(Employee(id="vera", name="Vera", role="analyst"))

    # Drive the REAL action-class DoD off the intent — this is the surface we are testing.
    verifier = analyst_dod(_INTENT)
    print(f"worktree : {mat.working_dir}")
    print(f"tools    : {mat.config.tools}")
    print(f"action   : {classify_action(_INTENT).value}  ->  DoD {verifier.kind.value}")
    print(f"intent   :\n{_INTENT}\n")

    outcome = await mat.runner.run_task(
        task_id="webres-1",
        intent=_INTENT,
        run_id="run-webres-1",
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
