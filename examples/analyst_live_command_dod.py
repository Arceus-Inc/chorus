"""Live Iteration-4 task — the objective Command DoD (dream runs a shell gate, no judgment).

Unlike the analyst's usual AgentReview DoD (a rubric an evaluator judges), the Command archetype is an
objective oracle: dream runs a shell command in the worktree and the beat passes iff it exits 0. Here
the gate (`python check.py`) asserts the analyst produced a well-formed `results.json` (numeric mean /
median / std) plus a non-empty `findings.md`. This exercises the Command DoD end to end.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/analyst_live_command_dod.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import statistics
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from chorus.events import Event, EventKind
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import EmployeeHarnessFactory

_VALUES = [12, 7, 19, 23, 5, 14, 9, 21, 16, 8, 27, 13, 6, 18, 11, 25, 10, 17, 4, 20]

_INTENT = (
    "A CSV `numbers.csv` is in your working directory with a single numeric column `value`. Compute the "
    "mean, median, and standard deviation of `value`, write them to a JSON file `results.json` with "
    "exactly the keys `mean`, `median`, `std` (numeric values), and write a short `findings.md` "
    "summarising the three statistics with their exact values."
)

# The objective Command DoD gate, seeded into the worktree and run by dream as the oracle.
_CHECK_PY = (
    "import json, os\n"
    "d = json.load(open('results.json'))\n"
    "for k in ('mean', 'median', 'std'):\n"
    "    assert isinstance(d.get(k), (int, float)), f'results.json missing numeric {k!r}'\n"
    "assert os.path.exists('findings.md') and os.path.getsize('findings.md') > 0, 'findings.md empty'\n"
    "print('OK: results.json well-formed and findings.md present')\n"
)


def _short(value: object, n: int = 220) -> str:
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
        print("skipping: set AZURE_OPENAI_API_KEY / AZURE_OPENAI_BASE_URL / AZURE_OPENAI_DEPLOYMENT")
        return 0

    roles = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=key, base_url=base, deployment=dep, company_id="analyst-command-dod",
        roles=roles, timeout_s=600.0,
    )
    mat = factory.materialize(Employee(id="vera", name="Vera", role="analyst"))
    (mat.working_dir / "numbers.csv").write_text(
        "value\n" + "\n".join(str(v) for v in _VALUES) + "\n", encoding="utf-8"
    )
    (mat.working_dir / "check.py").write_text(_CHECK_PY, encoding="utf-8")

    # The objective Command DoD (what a human would set via `dod set`): dream runs it as the gate.
    verifier = Verifier.command("python check.py", artifact_class="finding")
    print(f"worktree : {mat.working_dir}")
    print(f"DoD      : Command -> {verifier.verification_steps()[0].command!r}")
    print(f"expected : mean={statistics.mean(_VALUES)}, median={statistics.median(_VALUES)}, "
          f"std={statistics.pstdev(_VALUES):.4f} (sample std {statistics.stdev(_VALUES):.4f})\n")

    outcome = await mat.runner.run_task(
        task_id="cmddod-1", intent=_INTENT, run_id="run-cmddod-1",
        verification=verifier.verification_steps(), rubric=verifier.rubric(), observer=_print_event,
    )

    print(f"\npassed   = {outcome.passed}")
    print(f"summary  = {outcome.summary}")
    results = mat.working_dir / "results.json"
    if results.is_file():
        print(f"\nresults.json: {results.read_text(encoding='utf-8')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
