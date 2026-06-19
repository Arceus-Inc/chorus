"""A manager + 2 engineers + 1 reviewer org runs 3 goals through the full reviewed-build suite.

Drives the REAL kernel over REAL worktrees with REAL subprocess builds (`python -m pytest -q`). The
model beats are scripted (the live reviewer's dream-harness tool-calling is covered separately — see
REVIEWER.md), but every kernel decision and every build is real, so this faithfully exercises the whole
reviewer suite end to end:

    Goal 1 — clean:        engineers build passing code → reviewer approves → kernel build passes → DONE
    Goal 2 — build fails:  one child's tests FAIL → kernel build blocks it → REJECTED → the manager
                           reacts (submit_task a fix) → the fix passes → DONE
    Goal 3 — quality block: the reviewer blocks a weak diff (command never runs) → REJECTED → the
                           manager reacts → the redo is approved + builds → DONE

Writes reports/m3-org-reviewed-run.html.

    uv run python examples/m3_org_reviewed_run.py
"""

from __future__ import annotations

import asyncio
import html
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from chorus.heartbeat import IntegrateContextPacket, Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, ChildPlan, assign_task
from chorus.outcomes import LanderRegistry
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_employee.manager import manager_lander
from chorus_employee.reviewer import reviewer_lander

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m3-org-reviewed-run.html"
_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)

_PASSING = "def f(x):\n    return x.strip().lower()\n"
_PASSING_TEST = "from app import f\n\ndef test_f():\n    assert f(' Hi ') == 'hi'\n"
_FAILING_TEST = "from app import f\n\ndef test_f():\n    assert f(' Hi ') == 'WRONG'\n"


@dataclass
class Event:
    kind: str
    detail: str


@dataclass
class GoalRun:
    name: str
    goal: str
    events: list[Event] = field(default_factory=list)
    children: dict[str, str] = field(default_factory=dict)  # label -> status
    verdicts: list[str] = field(default_factory=list)
    final_status: str = ""
    manager_beats: int = 0


class _Engineer:
    """Writes real code into its worktree. A 'buggy' child writes a failing test; others pass."""

    def __init__(self, worktree: Path, run: GoalRun) -> None:
        self.working_dir = worktree
        self._run = run

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        buggy = "buggy" in intent
        (self.working_dir / "app.py").write_text(_PASSING, encoding="utf-8")
        (self.working_dir / "test_app.py").write_text(
            _FAILING_TEST if buggy else _PASSING_TEST, encoding="utf-8"
        )
        self._run.events.append(Event("engineer", f"built {'(buggy)' if buggy else '(clean)'}: {intent[:60]}"))
        return BeatOutcome(passed=True, outcome={}, summary="built", model="scripted")


class _Reviewer:
    """Discovers the verify command + judges. Blocks a 'weak' child on quality; else approves."""

    def __init__(self, ledger: SqliteLedger, worktree: Path, run: GoalRun, *, reviewer_id: str) -> None:
        self._ledger = ledger
        self.working_dir = worktree
        self._run = run
        self._id = reviewer_id

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        approve = "weak" not in intent  # a quality block for a deliberately weak diff
        command = "python -m pytest -q" if (self.working_dir / "test_app.py").exists() else "true"
        CapabilityService(self._ledger).record_verdict(
            task_id=task_id, run_id=str(run_id), reviewer_id=self._id, approve=approve,
            feedback="meets the rubric" if approve else "weak: missing real logic", verify_command=command,
        )
        self._run.verdicts.append(f"{'approve' if approve else 'BLOCK'} · cmd=`{command}` · {intent[:40]}")
        return BeatOutcome(passed=True, outcome={}, summary="reviewed", model="scripted")


class _Manager:
    """Decompose on kickoff; on integrate, react to a rejected child with one submit_task, else accept."""

    def __init__(self, ledger: SqliteLedger, worktree: Path, run: GoalRun, *, parent: str,
                 plan: list[ChildPlan]) -> None:
        self.working_dir = worktree
        self._ledger = ledger
        self._run = run
        self._parent = parent
        self._plan = plan
        self._fixed = False

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        self._run.manager_beats += 1
        svc = CapabilityService(self._ledger)
        if not self._ledger.tasks.has_children(self._parent):
            svc.decompose(parent_id=self._parent, revision=str(run_id), children=self._plan)
            self._run.events.append(Event("manager", f"decomposed into {[c.label for c in self._plan]}"))
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="scripted")
        if IntegrateContextPacket.recommended_for(self._ledger, self._parent) == "react" and not self._fixed:
            self._fixed = True
            svc.submit_one(parent_id=self._parent, revision=str(run_id),
                           child=ChildPlan(label="fix", intent="fix the rejected work", assignee="bob"))
            self._run.events.append(Event("manager", "reacted to a rejection → submit_task('fix' → bob)"))
            return BeatOutcome(passed=False, outcome={}, summary="reacted", model="scripted")
        self._run.events.append(Event("manager", "accepted the completed subtree"))
        return BeatOutcome(passed=True, outcome={}, summary="accepted", model="scripted")


class _Org:
    def __init__(self, ledger: SqliteLedger, run: GoalRun, base: Path, *, parent: str,
                 plan: list[ChildPlan]) -> None:
        self._ledger = ledger
        self._run = run
        self._base = base
        self._parent = parent
        self._plan = plan

    def _worktree(self, employee_id: str) -> Path:
        wt = self._base / "worktrees" / employee_id
        wt.mkdir(parents=True, exist_ok=True)
        return wt

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> object:
        return self._for(employee, self._worktree(employee.id))

    def review_runner_for(self, reviewer: Employee, *, task_id: str, worktree_owner_id: str) -> object:
        return _Reviewer(self._ledger, self._worktree(worktree_owner_id), self._run, reviewer_id=reviewer.id)

    def _for(self, employee: Employee, worktree: Path) -> object:
        if employee.role == "manager":
            return _Manager(self._ledger, worktree, self._run, parent=self._parent, plan=self._plan)
        if employee.role == "reviewer":
            return _Reviewer(self._ledger, worktree, self._run, reviewer_id=employee.id)
        return _Engineer(worktree, self._run)


async def _run_goal(name: str, goal: str, plan: list[ChildPlan]) -> GoalRun:
    run = GoalRun(name=name, goal=goal)
    base = Path(tempfile.mkdtemp(prefix="chorus-org-"))
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="moe"))
        ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="moe"))
        ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
        ledger.tasks.submit(Task(id="G", intent=goal, status=TaskStatus.TODO))
        assign_task(ledger, "G", "moe")
        org = _Org(ledger, run, base, parent="G", plan=plan)
        landers = LanderRegistry.from_landers([manager_lander(ledger), reviewer_lander(ledger)])
        sched = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner_for=org,  # type: ignore[arg-type]
            roles=RoleRegistry.from_plugins(default_roles()), landers=landers,
            clock=lambda: _NOW, max_concurrent_runs=4, max_review_rounds=1, max_integrate_iterations=4,
        )
        for _ in range(20):
            g = ledger.tasks.get("G")
            if g is not None and g.status is TaskStatus.DONE:
                break
            await sched.tick_once()
            await sched.drain()
        run.children = {c.origin_fingerprint: c.status.value for c in ledger.tasks.children("G")}
        g = ledger.tasks.get("G")
        run.final_status = g.status.value if g is not None else "?"
        return run
    finally:
        ledger.close()


def _render(runs: list[GoalRun]) -> str:
    def esc(v: object) -> str:
        return html.escape(str(v))

    cards = []
    for r in runs:
        ok = r.final_status == "done"
        badge = "<span class='ok'>DONE</span>" if ok else f"<span class='no'>{esc(r.final_status)}</span>"
        evs = "".join(f"<li><b>{esc(e.kind)}</b>: {esc(e.detail)}</li>" for e in r.events)
        verds = "".join(f"<li>{esc(v)}</li>" for v in r.verdicts)
        kids = "".join(
            f"<tr><td><code>{esc(label)}</code></td><td>{esc(status)}</td></tr>"
            for label, status in r.children.items()
        )
        cards.append(f"""
        <section class="card"><div class="head"><h2>{esc(r.name)}</h2>{badge}</div>
          <p class="goal">{esc(r.goal)}</p>
          <div class="cols">
            <div><h3>timeline</h3><ul>{evs}</ul><h3>reviewer verdicts</h3><ul class="v">{verds}</ul></div>
            <div><h3>children (final)</h3><table>{kids}</table>
                 <p class="muted">manager beats: {r.manager_beats}</p></div>
          </div></section>""")
    overall = "ALL 3 GOALS COMPLETED" if all(r.final_status == "done" for r in runs) else "SOME GOALS INCOMPLETE"
    cls = "ok" if all(r.final_status == "done" for r in runs) else "no"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>manager + 2 engineers + reviewer — reviewed-build run</title><style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e8eb}}
h1{{font-size:1.45rem}} .lead{{color:#9aa0a6;max-width:74ch}}
.overall{{display:inline-block;padding:.4rem .9rem;border-radius:999px;font-weight:800;margin:1rem 0}}
.overall.ok{{background:#0e3a23;color:#4ade80}} .overall.no{{background:#3a0e12;color:#f87171}}
.card{{background:#16191f;border:1px solid #262b33;border-radius:12px;padding:1rem 1.3rem;margin-bottom:1.3rem}}
.head{{display:flex;justify-content:space-between;align-items:center}} h2{{font-size:1.15rem;margin:.2rem 0}}
h3{{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:#9aa0a6;margin:.9rem 0 .3rem}}
.goal{{color:#cbd5e1}} .cols{{display:flex;gap:2rem;flex-wrap:wrap}} .cols>div{{flex:1;min-width:280px}}
ul{{margin:.2rem 0;padding-left:1.1rem;font-size:.88rem}} ul.v li{{font-family:ui-monospace,monospace;font-size:.8rem}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}} td{{padding:.25rem .4rem;border-bottom:1px solid #262b33}}
code{{background:#0f1115;padding:.1rem .3rem;border-radius:4px}} .muted{{color:#6b7280;font-size:.82rem}}
.ok{{color:#4ade80;font-weight:800}} .no{{color:#f87171;font-weight:800}}
</style></head><body>
<h1>manager + 2 engineers + reviewer — 3 goals through the reviewed-build suite</h1>
<p class="lead">Real kernel, real worktrees, real <code>pytest</code> builds. The manager decomposes;
engineers build; a read-only reviewer discovers the verify command + judges; the <b>kernel runs the
command</b> as the objective floor; a block (quality or failed build) becomes a <code>REJECTED</code>
child the manager reacts to. Model beats are scripted; every build + kernel decision is real.</p>
<div class="overall {cls}">{overall}</div>
{''.join(cards)}
<footer class="muted">Generated by examples/m3_org_reviewed_run.py · chorus M3 reviewed-build</footer>
</body></html>"""


def main() -> int:
    goals = [
        ("Goal 1 · clean build", "Build a slugify utility with a unit test.",
         [ChildPlan(label="slugify", intent="implement slugify with a test", assignee="ada"),
          ChildPlan(label="shout", intent="implement shout with a test", assignee="bob")]),
        ("Goal 2 · failing build → manager reacts", "Build a parser; the first cut has a failing test.",
         [ChildPlan(label="core", intent="implement the buggy parser core with a test", assignee="ada")]),
        ("Goal 3 · quality block → manager reacts", "Write a validator; the first diff is too weak.",
         [ChildPlan(label="weak", intent="implement a weak validator with a test", assignee="ada")]),
    ]
    runs = [asyncio.run(_run_goal(name, goal, plan)) for name, goal, plan in goals]

    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(_render(runs), encoding="utf-8")
    for r in runs:
        sys.stdout.write(f"{r.name}: final={r.final_status}  children={r.children}  verdicts={len(r.verdicts)}\n")
    sys.stdout.write(f"\nHTML report: {_REPORT}\n")
    ok = all(r.final_status == "done" for r in runs)
    sys.stdout.write("\n✅ all 3 goals completed through the reviewed-build suite\n" if ok
                     else "\n⚠️ some goals did not complete (see report)\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
