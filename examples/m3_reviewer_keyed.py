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
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.ledger import Ledger, Task, TaskStatus
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
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=s",
            "-c",
            "user.email=s@x",
            "commit",
            "-m",
            "seed",
        ],
        check=True,
        capture_output=True,
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

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    try:
        LedgerWorkforce(ledger.employees).hire(name="pen", role="pm")
        LedgerWorkforce(ledger.employees).hire(name="rob", role="reviewer")
        ledger.tasks.submit(Task(id="spec", intent=_GOAL, status=TaskStatus.TODO))
        assign_task(ledger, "spec", "pen")

        runner = build_beat_service(
            ledger,
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            pricing=default_pricing_from_env(),
            seed=seed,
            work_root=base / "work",
            max_concurrent_runs=2,
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
            verdicts = [
                a
                for a in ledger.activity.by_subject("task", "spec")
                if a.verb.value == "review_verdict"
            ]
            _log(
                f"tick {n}: spec={task.status.value if task else '?'}  "
                f"review_verdicts={[v.payload.get('approve') for v in verdicts]}"
            )

        task = ledger.tasks.get("spec")
        status = task.status.value if task else "?"
        artifacts = [a for a in ledger.artifacts.list_for_task("spec") if a.type.value == "verdict"]
        review_runs = [r for r in ledger.runs.for_task("spec") if r.employee_id == "rob"]
        recovery = ledger.recovery_actions.active_for_source("spec")
        _log("\n" + "=" * 72)
        _log(f"final status: {status}")
        _log(f"reviewer beats run: {len(review_runs)}   verdict artifacts: {len(artifacts)}")
        for art in artifacts:
            ref = art.resource_ref or {}
            _log(
                f"   verdict: approve={ref.get('approve')}  reviewer={ref.get('reviewer')}  "
                f"feedback={str(ref.get('feedback'))[:120]}"
            )
        if recovery is not None:
            _log(
                f"recovery card open: cause={recovery.cause}  (a human now owns the rejected/unverified work)"
            )

        # The load-bearing guarantee: a leaf agent_review deliverable is GATED by the reviewer — it can
        # never reach `done` without a recorded approve verdict. So either:
        #   • DONE  → there is an approve verdict artifact (the happy path), or
        #   • not DONE → it is safely held (blocked/rejected + recovery, or self-repair) — never a silent pass.
        # NOTE (live tuning): with the current dream harness the reviewer beat reliably runs and inspects
        # the work, but the model does not always emit the `submit_verdict` tool call; when it doesn't,
        # the kernel correctly blocks + opens a recovery card rather than passing unverified. The kernel
        # orchestration + every branch is proven deterministically in tests/heartbeat/test_m3_review.py.
        gated = (
            status == "done"
            and any(a.resource_ref and a.resource_ref.get("approve") for a in artifacts)
        ) or (status != "done" and len(review_runs) >= 1)
        _log(
            "\n✅ the deliverable was GATED by the Reviewer (never a silent pass)"
            if gated
            else "❌ the deliverable was not gated — investigate"
        )
        return 0 if gated else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
