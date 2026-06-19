"""Keyed M3 Slice-2 demo — watch the adaptive manager loop AND its observability evolve.

Runs the real manager loop with a live model (manager + two engineers), and at each meaningful state
change snapshots the two observability surfaces Pranjal wired into the CLI:

    check org           -> LedgerInspector.org_report()      (org-wide rollup)
    check scrum <goal>  -> LedgerInspector.scrum_packet(goal) (the manager's Scrum packet)

So you see the packet's `iteration`, completion rate, child outcomes, and routing churn change across
the decompose -> park -> integrate (-> submit follow-up -> re-integrate) cycle — and that the Slice-2
fixes hold (no over-decompose ballooning; the loop terminates).

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/m3_observability_demo.py

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
from chorus.observability import LedgerInspector
from chorus.observability._views import OrgObservabilityReport, ScrumPacketView
from chorus.workforce import LedgerWorkforce
from chorus_cli._beats import build_beat_service, default_pricing_from_env

_GOAL = "Build a small Python text-utilities library with a slugify and a shout function."
_MAX_TICKS = 16


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# text utils\n", encoding="utf-8")
    (path / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "seed"],
        check=True, capture_output=True,
    )


def _render_org(org: OrgObservabilityReport) -> str:
    return (
        f"  employees={org.employees} (managers={org.managers}, leaves={org.leaves})  "
        f"tasks: {org.tasks_done}/{org.tasks_total} done, {org.tasks_blocked} blocked  "
        f"running_beats={org.running_beats}"
    )


def _render_scrum(p: ScrumPacketView) -> str:
    lines = [
        f"  goal {p.parent_task_id} (manager={p.manager_id})  ITERATION={p.iteration}",
        f"  intent: {p.parent_intent[:80]}",
        f"  children={p.child_count}  done={p.completed_children}  blocked={p.blocked_children}  "
        f"completion={p.completion_rate:.0%}",
        f"  deps={p.dependency_edges}  assignments={p.assignment_count}  reassignments={p.reassignments}",
    ]
    for c in p.children:
        lines.append(
            f"    - {c.label:<14} [{c.assignee}/{c.assignee_role}]  {c.status:<11} "
            f"dod={c.dod_status}  run={c.latest_run_status}  art={c.artifact_type}"
        )
    return "\n".join(lines)


def _snapshot(inspector: LedgerInspector, ledger: SqliteLedger, goal_id: str, *, n: int) -> None:
    _log(f"\n{'─' * 70}\n📊 OBSERVABILITY SNAPSHOT {n}\n{'─' * 70}")
    _log("`check org`  →  org_report():")
    _log(_render_org(inspector.org_report()))
    if ledger.tasks.has_children(goal_id):
        _log(f"\n`check scrum {goal_id}`  →  scrum_packet():")
        _log(_render_scrum(inspector.scrum_packet(goal_id)))
    else:
        _log(f"\n`check scrum {goal_id}`  →  (no children yet — the manager hasn't decomposed)")


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-obs-"))
    os.chdir(base)
    seed = base / "seed"
    _seed_repo(seed)

    ledger = SqliteLedger.open(str(base / "ledger.db"))
    try:
        for emp, role in [("moe", "manager"), ("ada", "engineer"), ("bob", "engineer")]:
            LedgerWorkforce(ledger.employees).hire(
                name=emp, role=role, reports_to="moe" if role == "engineer" else None
            )
        ledger.tasks.submit(Task(id="goal", intent=_GOAL, status=TaskStatus.TODO))
        assign_task(ledger, "goal", "moe")

        runner = build_beat_service(
            ledger, api_key=api_key, base_url=base_url, deployment=deployment, company_id="acme",
            pricing=default_pricing_from_env(), seed=seed, work_root=base / "work", max_concurrent_runs=2,
        )
        inspector = LedgerInspector(ledger)

        _log("=" * 70)
        _log("ADAPTIVE MANAGER LOOP — one manager (moe) + two engineers (ada, bob)")
        _log(f"goal: {_GOAL}")
        _log("=" * 70)

        snapshots = 0
        last_state: tuple[object, ...] = ()
        for n in range(1, _MAX_TICKS + 1):
            goal = ledger.tasks.get("goal")
            if goal is not None and goal.status is TaskStatus.DONE:
                break
            runner.run_tick()
            kids = ledger.tasks.children("goal")
            state = (
                ledger.tasks.get("goal").status.value,  # type: ignore[union-attr]
                tuple((c.id[-4:], c.status.value) for c in kids),
            )
            _log(f"\ntick {n}: goal={state[0]}  children={list(state[1])}")
            # Snapshot the observability whenever the loop's state actually changed (2-3 meaningful points).
            if state != last_state:
                snapshots += 1
                _snapshot(inspector, ledger, "goal", n=snapshots)
                last_state = state

        # Final snapshot — the integrated result + closing observability.
        snapshots += 1
        _snapshot(inspector, ledger, "goal", n=snapshots)

        goal = ledger.tasks.get("goal")
        _log("\n" + "=" * 70)
        ok = goal is not None and goal.status is TaskStatus.DONE
        manager_beats = len([r for r in ledger.runs.for_task("goal")])
        _log(f"goal status: {goal.status.value if goal else '?'}  |  manager beats on goal: {manager_beats} "
             f"(1 kickoff + {manager_beats - 1} integrate)")
        _log(f"children created: {len(ledger.tasks.children('goal'))} "
             "(bounded — the integrate beat cannot re-decompose)")
        _log("✅ loop closed + observability captured" if ok else "⚠️ loop did not fully close (see snapshots)")
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
