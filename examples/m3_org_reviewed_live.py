"""3 goals through a manager + 2 engineers + a LIVE reviewer — the full reviewed-build suite, for real.

The manager + engineers are scripted (the engineers write *real* code into real worktrees), but the
**reviewer is a live model**: the kernel materializes it read-only at the engineer's worktree, it reads
the real diff, discovers the project's verify command, and calls ``submit_verdict`` for real. The kernel
then runs that command as the objective floor. So the verdict + the discovered command are genuinely the
model's; the build + every kernel decision are real.

    Goal 1 — clean code       → live reviewer judges → kernel build (pytest) → expect DONE
    Goal 2 — buggy code        → kernel build fails (or the reviewer blocks) → REJECTED → manager reacts → DONE
    Goal 3 — incomplete stub   → live reviewer / build gate it → REJECTED → manager reacts → DONE

Writes reports/m3-org-reviewed-live.html. Skips cleanly (exit 0) when the Azure env vars are unset.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/m3_org_reviewed_live.py
"""

from __future__ import annotations

import asyncio
import html
import os
import subprocess
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
from chorus.workspace import CompanyWorkspace
from chorus_cli._beats import default_pricing_from_env
from chorus_employee.manager import manager_lander
from chorus_employee.reviewer import reviewer_lander
from chorus_harness import EmployeeHarnessFactory

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m3-org-reviewed-live.html"
_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)

# The precise, testable contract every slugify task carries. A vague intent ("implement slugify") lets a
# strict live reviewer invent its own acceptance criteria and block almost anything; an explicit contract
# anchors the verdict to the real spec — which is exactly what `_CLEAN` implements.
_CONTRACT = (
    "Implement slugify(s) in app.py with this exact contract: lowercase the input, replace every run of "
    "non-alphanumeric characters (whitespace, punctuation, underscores) with a single hyphen, and strip "
    "leading and trailing hyphens. Examples: ' Hi There ' -> 'hi-there'; 'Hello, World!' -> 'hello-world'; "
    "'foo_bar  baz' -> 'foo-bar-baz'; '--A__B--' -> 'a-b'. Add a pytest test in test_app.py covering "
    "whitespace, punctuation, and underscores."
)

# Real Python the engineer "writes" — clean / buggy (failing test) / incomplete stub.
# _CLEAN is a complete, defensible slugify (lowercases, maps every non-alphanumeric run to a single
# hyphen — so spaces, punctuation, and underscores collapse — and trims leading/trailing hyphens), with a
# test that covers those cases. It is written to genuinely pass a strict live review, not to flatter it.
_CLEAN = (
    "app.py",
    "import re\n\n\n"
    "def slugify(s):\n"
    '    """Lowercase, collapse every non-alphanumeric run to one hyphen, trim hyphens."""\n'
    '    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")\n',
    "test_app.py",
    "from app import slugify\n\n\n"
    "def test_whitespace():\n"
    "    assert slugify(' Hi There ') == 'hi-there'\n\n\n"
    "def test_punctuation_and_underscores():\n"
    "    assert slugify('Hello, World!') == 'hello-world'\n"
    "    assert slugify('foo_bar  baz') == 'foo-bar-baz'\n"
    "    assert slugify('--A__B--') == 'a-b'\n",
)
_BUGGY = ("app.py", "def slugify(s):\n    return s  # TODO\n",
          "test_app.py", "from app import slugify\n\ndef test():\n    assert slugify(' Hi There ') == 'hi-there'\n")
_STUB = ("app.py", "def slugify(s):\n    raise NotImplementedError\n", "", "")


@dataclass
class GoalRun:
    name: str
    goal: str
    code: tuple[str, str, str, str]
    events: list[str] = field(default_factory=list)
    children: dict[str, str] = field(default_factory=dict)
    verdicts: list[dict[str, object]] = field(default_factory=list)
    final_status: str = ""


class _Engineer:
    def __init__(self, worktree: Path, run: GoalRun) -> None:
        self.working_dir = worktree
        self._run = run

    async def run_task(self, *, task_id: str, intent: str, verification: object = (),
                       observer: object = None, run_id: str | None = None) -> BeatOutcome:
        # A "fix" beat (the manager's reaction to a rejection) always writes the complete _CLEAN code;
        # the initial beat writes the goal's code. Case-insensitive so a "Fix the rejected work" intent
        # still routes to the clean implementation.
        name, body, tname, tbody = _CLEAN if "fix" in intent.lower() else self._run.code
        self.working_dir.mkdir(parents=True, exist_ok=True)
        (self.working_dir / name).write_text(body, encoding="utf-8")
        if tname:
            (self.working_dir / tname).write_text(tbody, encoding="utf-8")
        self._run.events.append(f"engineer built ({'fix' if 'fix' in intent else 'initial'}): {intent[:50]}")
        return BeatOutcome(passed=True, outcome={}, summary="built", model="scripted")


class _Manager:
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
        svc = CapabilityService(self._ledger)
        if not self._ledger.tasks.has_children(self._parent):
            svc.decompose(parent_id=self._parent, revision=str(run_id), children=self._plan)
            self._run.events.append(f"manager decomposed into {[c.label for c in self._plan]}")
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="scripted")
        if IntegrateContextPacket.recommended_for(self._ledger, self._parent) == "react" and not self._fixed:
            self._fixed = True
            svc.submit_one(parent_id=self._parent, revision=str(run_id),
                           child=ChildPlan(label="fix", intent=f"Fix the rejected work. {_CONTRACT}",
                                           assignee="bob"))
            self._run.events.append("manager reacted to a rejection → submit_task('fix' → bob)")
            return BeatOutcome(passed=False, outcome={}, summary="reacted", model="scripted")
        self._run.events.append("manager accepted the completed subtree")
        return BeatOutcome(passed=True, outcome={}, summary="accepted", model="scripted")


class _Org:
    """Scripted manager + engineers; the reviewer is delegated to the LIVE factory."""

    def __init__(self, ledger: SqliteLedger, run: GoalRun, *, parent: str, plan: list[ChildPlan],
                 factory: EmployeeHarnessFactory, workspace: CompanyWorkspace, mgr_dir: Path) -> None:
        self._ledger = ledger
        self._run = run
        self._parent = parent
        self._plan = plan
        self._factory = factory
        self._workspace = workspace
        self._mgr_dir = mgr_dir

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> object:
        if employee.role == "manager":
            return _Manager(self._ledger, self._mgr_dir, self._run, parent=self._parent, plan=self._plan)
        return _Engineer(self._workspace.worktree_for(employee.id).path, self._run)

    def review_runner_for(self, reviewer: Employee, *, task_id: str, worktree_owner_id: str) -> object:
        # the LIVE reviewer — materialized read-only at the engineer's worktree
        return self._factory.review_runner_for(
            reviewer, task_id=task_id, worktree_owner_id=worktree_owner_id
        )


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# org\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "seed"],
                   check=True, capture_output=True)


async def _run_goal(run: GoalRun, plan: list[ChildPlan], *, api_key: str, base_url: str, deployment: str) -> GoalRun:
    base = Path(tempfile.mkdtemp(prefix="chorus-live-"))
    seed = base / "seed"
    _seed_repo(seed)
    lg = SqliteLedger.open(str(base / "ledger.db"))
    try:
        for emp, role in [("moe", "manager"), ("ada", "engineer"), ("bob", "engineer"), ("rob", "reviewer")]:
            LedgerWorkforce(lg.employees).hire(name=emp, role=role,
                                               reports_to="moe" if role == "engineer" else None)
        lg.tasks.submit(Task(id="G", intent=run.goal, status=TaskStatus.TODO))
        assign_task(lg, "G", "moe")
        factory = EmployeeHarnessFactory(
            api_key=api_key, base_url=base_url, deployment=deployment, company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()), pricing=default_pricing_from_env(),
            seed=seed, work_root=base / "work", ledger=lg,
        )
        workspace = CompanyWorkspace(factory.company_root, seed=seed)
        for emp in ("ada", "bob"):  # pre-create the engineer worktrees the scripted beats write into
            workspace.worktree_for(emp)
        org = _Org(lg, run, parent="G", plan=plan, factory=factory, workspace=workspace, mgr_dir=base / "mgr")
        (base / "mgr").mkdir(parents=True, exist_ok=True)
        landers = LanderRegistry.from_landers([manager_lander(lg), reviewer_lander(lg)])
        sched = Scheduler(
            ledger=lg, workforce=LedgerWorkforce(lg.employees), beat_runner_for=org,  # type: ignore[arg-type]
            roles=RoleRegistry.from_plugins(default_roles()), landers=landers,
            clock=lambda: _NOW, max_concurrent_runs=2, max_review_rounds=1, max_integrate_iterations=4,
        )
        for _ in range(24):
            g = lg.tasks.get("G")
            if g is not None and g.status is TaskStatus.DONE:
                break
            await sched.tick_once()
            await sched.drain()

        run.children = {c.origin_fingerprint: c.status.value for c in lg.tasks.children("G")}
        for child in lg.tasks.children("G"):
            dod = lg.dod.get_for_task(child.id)
            if dod is not None and dod.verdict is not None:
                run.verdicts.append({"child": child.origin_fingerprint, **dod.verdict})
        g = lg.tasks.get("G")
        run.final_status = g.status.value if g is not None else "?"
        return run
    finally:
        lg.close()


def _verdict_html(v: dict[str, object], esc: object) -> str:
    e = esc  # type: ignore[assignment]
    decision = "approve" if v.get("approve") else "BLOCK"
    cls = "ok" if v.get("approve") else "no"
    parts = [f"<b>{e(v.get('child'))}</b> — <span class='{cls}'>{decision}</span>"]  # type: ignore[operator]
    cmd = v.get("verify_command")
    if cmd:
        parts.append(f" · cmd <code>{e(cmd)}</code>")  # type: ignore[operator]
    bp = v.get("build_passed")
    if bp is not None:
        result = "pass" if bp else f"fail (exit {e(v.get('build_exit'))})"  # type: ignore[operator]
        parts.append(f" · build {result}")
    body = "".join(parts)
    fb = e(str(v.get("feedback"))[:400])  # type: ignore[operator]
    return f"<div class='verdict'>{body}<div class='fb'>{fb}</div></div>"


def _render(runs: list[GoalRun]) -> str:
    def esc(v: object) -> str:
        return html.escape(str(v))

    cards = []
    for r in runs:
        ok = r.final_status == "done"
        badge = "<span class='ok'>DONE</span>" if ok else f"<span class='no'>{esc(r.final_status)}</span>"
        evs = "".join(f"<li>{esc(e)}</li>" for e in r.events)
        kids = "".join(f"<tr><td><code>{esc(k)}</code></td><td>{esc(s)}</td></tr>" for k, s in r.children.items())
        verds = "".join(_verdict_html(v, esc) for v in r.verdicts)
        cards.append(f"""
        <section class="card"><div class="head"><h2>{esc(r.name)}</h2>{badge}</div>
          <p class="goal">{esc(r.goal)}</p>
          <h3>timeline</h3><ul>{evs}</ul>
          <h3>LIVE reviewer verdicts</h3>{verds or '<p class=muted>(no verdict recorded)</p>'}
          <h3>children (final)</h3><table>{kids}</table>
        </section>""")
    allok = all(r.final_status == "done" for r in runs)
    overall = "ALL 3 GOALS COMPLETED (live reviewer)" if allok else "SOME GOALS INCOMPLETE — see verdicts"
    cls = "ok" if allok else "no"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>manager + 2 engineers + LIVE reviewer</title><style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e8eb}}
h1{{font-size:1.45rem}} .lead{{color:#9aa0a6;max-width:74ch}}
.overall{{display:inline-block;padding:.4rem .9rem;border-radius:999px;font-weight:800;margin:1rem 0}}
.overall.ok{{background:#0e3a23;color:#4ade80}} .overall.no{{background:#3a0e12;color:#f87171}}
.card{{background:#16191f;border:1px solid #262b33;border-radius:12px;padding:1rem 1.3rem;margin-bottom:1.3rem}}
.head{{display:flex;justify-content:space-between;align-items:center}} h2{{font-size:1.15rem;margin:.2rem 0}}
h3{{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:#9aa0a6;margin:.9rem 0 .3rem}}
.goal{{color:#cbd5e1}} ul{{margin:.2rem 0;padding-left:1.1rem;font-size:.88rem}}
.verdict{{background:#0f1115;border-left:3px solid #3b82f6;padding:.5rem .7rem;border-radius:4px;margin:.4rem 0;font-size:.86rem}}
.fb{{color:#9aa0a6;margin-top:.3rem;font-size:.82rem;white-space:pre-wrap}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}} td{{padding:.25rem .4rem;border-bottom:1px solid #262b33}}
code{{background:#0f1115;padding:.1rem .3rem;border-radius:4px}} .muted{{color:#6b7280}}
.ok{{color:#4ade80;font-weight:800}} .no{{color:#f87171;font-weight:800}}
</style></head><body>
<h1>manager + 2 engineers + <em>live</em> reviewer — 3 goals, reviewed-build suite</h1>
<p class="lead">Manager + engineers are scripted (engineers write real code); the <b>reviewer is a live
model</b> that reads the real diff, discovers the verify command, and renders the verdict. The kernel
runs that command for real. The verdicts + feedback below are the model's own words.</p>
<div class="overall {cls}">{overall}</div>
{''.join(cards)}
<footer class="muted">examples/m3_org_reviewed_live.py · chorus M3 reviewed-build (live reviewer)</footer>
</body></html>"""


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        sys.stdout.write("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT\n")
        return 0

    specs = [
        (GoalRun("Goal 1 · clean code", f"Build a slugify utility. {_CONTRACT}", _CLEAN),
         [ChildPlan(label="slugify", intent=_CONTRACT, assignee="ada")]),
        (GoalRun("Goal 2 · buggy build", f"Build slugify; the first cut has a failing test. {_CONTRACT}", _BUGGY),
         [ChildPlan(label="core", intent=_CONTRACT, assignee="ada")]),
        (GoalRun("Goal 3 · incomplete stub", f"Build slugify; the first diff is an unfinished stub. {_CONTRACT}", _STUB),
         [ChildPlan(label="stub", intent=_CONTRACT, assignee="ada")]),
    ]
    runs: list[GoalRun] = []
    for run, plan in specs:
        sys.stdout.write(f"\n=== {run.name} ===\n")
        sys.stdout.flush()
        runs.append(asyncio.run(_run_goal(run, plan, api_key=api_key, base_url=base_url, deployment=deployment)))
        r = runs[-1]
        sys.stdout.write(f"  final={r.final_status}  children={r.children}\n")
        for v in r.verdicts:
            sys.stdout.write(f"  verdict[{v.get('child')}]: approve={v.get('approve')} "
                             f"cmd={v.get('verify_command')!r} build_passed={v.get('build_passed')}\n")

    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(_render(runs), encoding="utf-8")
    sys.stdout.write(f"\nHTML report: {_REPORT}\n")
    return 0 if all(r.final_status == "done" for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
