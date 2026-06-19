"""Keyed M3 e2e — a live, load-bearing Reviewer gates a real judgment deliverable.

A PM writes a short spec in its own worktree; because the PM's DoD is ``agent_review``, the kernel
dispatches a READ-ONLY Reviewer beat at the PM's worktree. The reviewer reads the spec, judges it
against the rubric, and calls ``submit_verdict`` — and that verdict IS the DoD result: approve lands the
task ``done`` with a ``verdict`` artifact; block routes it to bounded self-repair (no manager here).

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/m3_reviewer_keyed.py

Skips cleanly (exit 0) when the Azure env vars are unset.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.workforce import LedgerWorkforce
from chorus_cli._beats import build_beat_service, default_pricing_from_env

_GOAL = (
    "Write a one-paragraph specification for a `slugify(text: str) -> str` function in a file named "
    "spec.md: state the inputs, the transformation (lowercase, spaces and punctuation to single "
    "hyphens, trimmed), and one worked example."
)
_MAX_TICKS = 12


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# specs\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "seed"],
        check=True, capture_output=True,
    )


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-reviewer-"))
    os.chdir(base)
    seed = base / "seed"
    _seed_repo(seed)

    ledger = SqliteLedger.open(str(base / "ledger.db"))
    try:
        LedgerWorkforce(ledger.employees).hire(name="pen", role="pm")
        LedgerWorkforce(ledger.employees).hire(name="rob", role="reviewer")
        ledger.tasks.submit(Task(id="spec", intent=_GOAL, status=TaskStatus.TODO))
        assign_task(ledger, "spec", "pen")

        runner = build_beat_service(
            ledger, api_key=api_key, base_url=base_url, deployment=deployment, company_id="acme",
            pricing=default_pricing_from_env(), seed=seed, work_root=base / "work", max_concurrent_runs=2,
        )

        _log("=" * 72)
        _log("LIVE REVIEWER e2e — a PM writes a spec; a read-only Reviewer gates it")
        _log(f"goal: {_GOAL}")
        _log("=" * 72)

        for n in range(1, _MAX_TICKS + 1):
            task = ledger.tasks.get("spec")
            if task is not None and task.status in (TaskStatus.DONE, TaskStatus.REJECTED):
                break
            runner.run_tick()
            task = ledger.tasks.get("spec")
            verdicts = [a for a in ledger.activity.by_subject("task", "spec")
                        if a.verb.value == "review_verdict"]
            _log(f"tick {n}: spec={task.status.value if task else '?'}  "
                 f"review_verdicts={[v.payload.get('approve') for v in verdicts]}")

        task = ledger.tasks.get("spec")
        artifacts = [a for a in ledger.artifacts.list_for_task("spec") if a.type.value == "verdict"]
        _log("\n" + "=" * 72)
        _log(f"final status: {task.status.value if task else '?'}")
        for art in artifacts:
            ref = art.resource_ref or {}
            _log(f"verdict artifact: approve={ref.get('approve')}  reviewer={ref.get('reviewer')}")
            _log(f"   feedback: {str(ref.get('feedback'))[:160]}")
        # The load-bearing claim: a live reviewer beat actually ran and recorded a verdict (the DoD did
        # not silently pass). On approve the task is DONE; on block it self-repairs / parks — either way
        # the gate fired.
        ok = len(artifacts) >= 1
        _log("\n✅ the Reviewer gated the deliverable (verdict recorded)" if ok
             else "❌ no verdict recorded — the reviewer beat did not run")
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
