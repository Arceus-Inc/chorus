"""Reviewed-build reviewer report — the engineer's language-agnostic, review-gated DoD, end to end.

Drives the REAL kernel review path over REAL worktrees and REAL subprocess builds. A scripted reviewer
stands in for the model (it discovers the project's verify command + judges the diff); the kernel runs
that command for real and decides. Three scenarios show the gate:

    1. approve + a passing build  → DONE   (objective floor + quality both pass)
    2. approve + a failing build  → BLOCK  (the kernel-run command fails — un-rationalizable)
    3. quality block              → BLOCK  (the command never runs)

Writes a standalone HTML report to reports/m3-reviewed-build.html. No model / no keys needed — the
build commands are real, so this is a faithful e2e of the gate (the live model only varies *which*
command it picks, which the deterministic tests + the live keyed reviewer cover separately).

    uv run python examples/m3_reviewed_build_report.py
"""

from __future__ import annotations

import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org

import asyncio
import html
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, assign_task
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_employee import default_landers

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m3-reviewed-build.html"
_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


class _Worker:
    """The engineer beat — the code is already in the worktree, so it just 'produces' (passes)."""

    def __init__(self, worktree: Path) -> None:
        self.working_dir = worktree

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="built", model="scripted")


class _Reviewer:
    """A scripted reviewer: judges the diff (``approve``) and reports the project's ``verify_command``."""

    def __init__(
        self,
        ledger: Ledger,
        worktree: Path,
        *,
        reviewer_id: str,
        approve: bool,
        verify_command: str,
    ) -> None:
        self._ledger = ledger
        self.working_dir = worktree
        self._id = reviewer_id
        self._approve = approve
        self._cmd = verify_command

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        CapabilityService(self._ledger).record_verdict(
            task_id=task_id,
            run_id=str(run_id),
            reviewer_id=self._id,
            approve=self._approve,
            feedback="looks good" if self._approve else "needs work",
            verify_command=self._cmd,
        )
        return BeatOutcome(passed=True, outcome={}, summary="reviewed", model="scripted")


class _Org:
    def __init__(
        self, ledger: Ledger, worktree: Path, *, approve: bool, verify_command: str
    ) -> None:
        self._ledger = ledger
        self._worktree = worktree
        self._approve = approve
        self._cmd = verify_command

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> object:
        return self._for(employee)

    def review_runner_for(
        self, reviewer: Employee, *, task_id: str, worktree_owner_id: str
    ) -> object:
        return self._for(reviewer)

    def _for(self, employee: Employee) -> object:
        if employee.role == "reviewer":
            return _Reviewer(
                self._ledger,
                self._worktree,
                reviewer_id=employee.id,
                approve=self._approve,
                verify_command=self._cmd,
            )
        return _Worker(self._worktree)


@dataclass
class Scenario:
    name: str
    code: str
    approve: bool
    verify_command: str
    status: str = ""
    build_passed: object = None
    build_exit: object = None
    build_output: str = ""
    feedback: str = ""


async def _run_scenario(s: Scenario, *, base: Path) -> Scenario:
    worktree = base / s.name.replace(" ", "_")
    worktree.mkdir(parents=True)
    (worktree / "app.py").write_text(s.code, encoding="utf-8")

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    try:
        ledger.employees.create(Employee(id="dev", name="Dev", role="engineer"))
        ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
        ledger.tasks.submit(Task(id="code", intent=f"implement: {s.name}", status=TaskStatus.TODO))
        assign_task(ledger, "code", "dev")
        ledger.dod.create(
            "code", Verifier.reviewed_build(artifact_class="pr")
        )  # the engineer's gate
        org = _Org(ledger, worktree, approve=s.approve, verify_command=s.verify_command)
        sched = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=org,  # type: ignore[arg-type]
            roles=RoleRegistry.from_plugins(default_roles()),
            landers=default_landers(base, ledger=ledger),
            clock=lambda: _NOW,
            max_review_rounds=0,
        )
        await sched.tick_once()
        await sched.drain()

        task = ledger.tasks.get("code")
        s.status = task.status.value if task is not None else "?"
        dod = ledger.dod.get_for_task("code")
        verdict = dod.verdict if dod is not None and dod.verdict is not None else {}
        s.build_passed = verdict.get("build_passed")
        s.build_exit = verdict.get("build_exit")
        s.build_output = str(verdict.get("build_output", ""))
        s.feedback = str(verdict.get("feedback", ""))
        return s
    finally:
        ledger.close()


def _render(scenarios: list[Scenario]) -> str:
    def esc(v: object) -> str:
        return html.escape(str(v))

    def verdict_cell(s: Scenario) -> str:
        if s.status == "done":
            return "<span class='ok'>DONE</span>"
        return "<span class='no'>BLOCKED / not done</span>"

    rows = "".join(
        f"<tr><td><b>{esc(s.name)}</b><div class='muted'>reviewer: "
        f"{'approve' if s.approve else 'block'}</div></td>"
        f"<td><code>{esc(s.verify_command) or '—'}</code></td>"
        f"<td>{'—' if s.build_passed is None else ('pass' if s.build_passed else 'fail')}"
        f"{'' if s.build_exit is None else f' (exit {esc(s.build_exit)})'}</td>"
        f"<td>{verdict_cell(s)}</td>"
        f"<td><code>{esc(s.build_output[:200]) or esc(s.feedback)}</code></td></tr>"
        for s in scenarios
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Reviewed-build report</title><style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e8eb}}
h1{{font-size:1.4rem}} .lead{{color:#9aa0a6;max-width:72ch}}
table{{width:100%;border-collapse:collapse;margin-top:1.5rem;font-size:.9rem}}
th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid #262b33;vertical-align:top}}
th{{color:#9aa0a6}} code{{background:#16191f;padding:.1rem .3rem;border-radius:4px;word-break:break-word}}
.ok{{color:#4ade80;font-weight:700}} .no{{color:#f87171;font-weight:700}} .muted{{color:#6b7280;font-size:.85rem}}
</style></head><body>
<h1>Engineer reviewed-build — review gate report</h1>
<p class="lead">The engineer's DoD is a <b>reviewed build</b>: a read-only reviewer discovers the
project's verify command + judges the diff; the <b>kernel runs that command</b> as the objective floor.
Language-lock is gone (the command is discovered, not hardcoded) and a build can never pass by the
model's word — the exit code is the kernel's. Each row below ran a <b>real</b> command in a real
worktree.</p>
<table><thead><tr><th>scenario</th><th>discovered verify command</th><th>kernel build</th>
<th>outcome</th><th>evidence</th></tr></thead><tbody>{rows}</tbody></table>
<p class="muted">Generated by examples/m3_reviewed_build_report.py · chorus M3 reviewed-build</p>
</body></html>"""


def main() -> int:
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="chorus-rb-"))
    scenarios = [
        Scenario(
            "approve + passing build",
            'print("ok")\n',
            approve=True,
            verify_command="python3 app.py",
        ),
        Scenario(
            "approve + failing build",
            "import sys\nsys.exit(1)\n",
            approve=True,
            verify_command="python3 app.py",
        ),
        Scenario("quality block", 'print("ok")\n', approve=False, verify_command="python3 app.py"),
    ]
    done = [asyncio.run(_run_scenario(s, base=base)) for s in scenarios]

    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(_render(done), encoding="utf-8")
    for s in done:
        sys.stdout.write(
            f"{s.name}: status={s.status}  build_passed={s.build_passed}  exit={s.build_exit}\n"
        )
    sys.stdout.write(f"\nHTML report: {_REPORT}\n")
    # the gate is correct iff: approve+pass → done; approve+fail → not done; quality-block → not done
    ok = (
        done[0].status == "done"
        and done[0].build_passed is True
        and done[1].status != "done"
        and done[1].build_passed is False
        and done[2].status != "done"
        and done[2].build_passed is None
    )
    sys.stdout.write(
        "\n✅ reviewed-build gate behaves correctly\n" if ok else "\n❌ gate misbehaved\n"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
