"""The public facade, live — the §0 front door + every group, end to end (spec 14 F7).

The whole point of spec 14: ``from chorus import Chorus`` gives a two-tier kernel that is *simple on
top* (anyone can operate a company) and *complete underneath* (every niche capability is reachable
under its group). This script proves both against a real model:

    org = Chorus.build(..., beat_runner_for=factory.runner_for, landers=factory.landers)
    org.hire(...) ; task = org.submit(...) ; await org.run_forever() ; org.status()   # the front door
    org.inspect / governance / budgets / trust / routines / workforce / dod           # the groups

``chorus`` (the kernel) stays dream-free; ``chorus_harness`` (the execution layer) brings dream + creds
and plugs into the two injection seams — execution (``runner_for``) and landing (``landers``). A real
engineer beat runs the submitted task to ``done`` and its build lands; then one verb on each low-level
group is exercised. Writes ``reports/m1-public-facade.html``.

    set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
    uv run python examples/facade_two_tier_live.py

Skips cleanly (exit 0) when the Azure env vars are unset.
"""

from __future__ import annotations

import asyncio
import html
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import dream

from chorus import (
    ApprovalDecision,
    ApprovalGate,
    BudgetScope,
    Caps,
    Chorus,
    TaskStatus,
    TaskView,
    TrustPreset,
    Verifier,
    WorkforceStatus,
    default_roles,
)
from chorus.roles import RoleRegistry
from chorus_cli._beats import default_pricing_from_env
from chorus_harness import EmployeeHarnessFactory

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m1-public-facade.html"
_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})
_INTENT = (
    "Create a file greet.py containing exactly this and nothing else:\n\n"
    "def greet(name):\n    return f'hello {name}'\n\n"
    "Make the change directly in greet.py in the repository root."
)
_DOD = Verifier.command("python -c \"import greet; assert greet.greet('moe') == 'hello moe'\"")


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# greetings\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )


@dataclass
class GroupProbe:
    """One low-level group verb, exercised after the heartbeat is stopped (pure ledger ops)."""

    group: str
    verb: str
    ok: bool
    detail: str


def _probe(group: str, verb: str, call: object) -> GroupProbe:
    """Run a group verb, capturing success/failure so one miss never aborts the report."""
    try:
        detail = call() if callable(call) else str(call)
        return GroupProbe(group, verb, True, str(detail))
    except Exception as exc:
        return GroupProbe(group, verb, False, f"{type(exc).__name__}: {exc}")


async def _run_until_terminal(org: Chorus, task_id: str, *, timeout_s: float) -> TaskView:
    """Drive the public heartbeat (``run_forever``) until the task is terminal or the cap elapses."""
    runner = asyncio.create_task(org.run_forever())
    start = time.monotonic()
    try:
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(2.0)
            view = org.inspect.task(task_id)
            beat = view.latest_run.status if view.latest_run is not None else "-"
            _log(f"   … status={view.status.value} beat={beat}")
            if view.status in _TERMINAL:
                break
    finally:
        org.stop()
        await runner
    return org.inspect.task(task_id)


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-facade-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)
    org_repo = str(base / "org")
    memory_repo = str(base / "memory")

    # ── the execution layer: dream + creds + worktrees + landing (sibling to the dream-free kernel) ──
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key, base_url=base_url, deployment=deployment,
        company_id="acme", roles=registry, pricing=default_pricing_from_env(),
        seed=seed, work_root=base / "work",
    )

    # ── the front door (spec 14 §0): build once, then operate the company with flat verbs ──
    org = Chorus.build(
        db_path=str(base / "company.db"),
        org_repo=org_repo,
        memory_repo=memory_repo,
        dream=dream,
        beat_runner_for=factory.runner_for,   # ← the execution seam plugs in here
        landers=factory.landers,              # ← the landing seam rides along with it
        caps=Caps(tick_interval_s=0.5),
        company_id="acme",
    )

    _log(f"deployment={deployment}")
    _log("=" * 72)
    _log("§0 FRONT DOOR — build → hire → submit → run_forever → status")

    org.hire(name="moe", role="manager")
    org.hire(name="eng1", role="engineer", reports_to="moe")
    task = org.submit(_INTENT, assignee="eng1", dod=_DOD)
    _log(f"   hired moe (manager) + eng1 (engineer); submitted {task.id} → eng1")

    final = asyncio.run(_run_until_terminal(org, task.id, timeout_s=240.0))
    status: WorkforceStatus = org.status()
    beat_ran = final.latest_run is not None
    done = final.status is TaskStatus.DONE
    company_main = factory.company_root / "repo"
    landed = (company_main / "greet.py").exists()
    _log(f"   final: status={final.status.value} beat_ran={beat_ran} landed_to_main={landed}")
    _log(f"   status(): {len(status.employees)} employees, {status.open_tasks} open, "
         f"{status.running_beats} running")

    # ── the groups (spec 14 §2.2): one verb each, after the heartbeat is stopped (no new beats) ──
    _log("")
    _log("LOW-LEVEL GROUPS — one verb on each of the seven accessors")
    gate_target = org.submit("authorize the staging deploy")          # a backlog task to gate
    dod_target = org.submit("tidy the changelog", assignee="eng1", dod=Verifier.command("true"))

    def _governance() -> str:
        appr = org.governance.open_gate(
            gate_target.id, gate_kind=ApprovalGate.AUTHORIZATION, reason="staging sign-off"
        )
        pending = len(org.governance.approvals())
        org.governance.resolve(appr.id, decision=ApprovalDecision.APPROVE, by="moe")
        return f"opened gate ({pending} pending) → approved {appr.id}"

    def _budgets() -> str:
        org.budgets.set(BudgetScope.EMPLOYEE, "eng1", 500_00)
        return "eng1 capped at $500/mo"

    def _trust() -> str:
        org.trust.set_task(task.id, preset=TrustPreset.LOW_TRUST_REVIEW)
        return "task → low_trust_review"

    def _routines() -> str:
        view = org.routines.add(
            employee="eng1", intent_template="weekly dependency bump", schedule="0 9 * * 1"
        )
        return f"{view.id} (weekly), {len(org.routines.list())} total"

    def _workforce() -> str:
        return f"{org.workforce.export(org_repo)} employees → {org_repo}"

    def _dod() -> str:
        org.dod.revise(dod_target.id, Verifier.command("true && echo ok"), by="moe")
        return f"revised DoD of {dod_target.id}"

    probes = [
        _probe("org.inspect", "task / stuck / org_report",
               lambda: f"task={org.inspect.task(task.id).status.value}, "
                       f"stuck={len(org.inspect.stuck())}, "
                       f"done_rate={org.inspect.org_report().completion_rate:.0%}"),
        _probe("org.governance", "open_gate → approvals → resolve", _governance),
        _probe("org.budgets", "set(EMPLOYEE, …)", _budgets),
        _probe("org.trust", "set_task(preset=…)", _trust),
        _probe("org.routines", "add → list", _routines),
        _probe("org.workforce", "export", _workforce),
        _probe("org.dod", "revise", _dod),
    ]
    for p in probes:
        _log(f"   {'✅' if p.ok else '❌'} {p.group:<16} {p.verb:<34} {p.detail}")

    groups_ok = all(p.ok for p in probes)
    accepted = beat_ran and groups_ok  # the F7 bar: front door ran a real beat + every group reachable

    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(
        _render(
            deployment=deployment, status=status, final=final, beat_ran=beat_ran, done=done,
            landed=landed, company_main=company_main, probes=probes, accepted=accepted,
        ),
        encoding="utf-8",
    )
    _log("")
    _log(f"facade two-tier {'OK ✅' if accepted else 'INCOMPLETE ❌'}   report → {_REPORT}")
    return 0 if accepted else 1


def _render(
    *,
    deployment: str,
    status: WorkforceStatus,
    final: TaskView,
    beat_ran: bool,
    done: bool,
    landed: bool,
    company_main: Path,
    probes: list[GroupProbe],
    accepted: bool,
) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value))

    def row(label: str, ok: bool, detail: str) -> str:
        return f"<tr><td>{'✅' if ok else '❌'}</td><td>{esc(label)}</td><td><code>{esc(detail)}</code></td></tr>"

    front = "\n".join([
        row("Chorus.build(beat_runner_for=…, landers=…)", True, "two-tier kernel constructed"),
        row("hire (flat)", len(status.employees) >= 2, f"{len(status.employees)} employees"),
        row("submit (flat)", True, f"{esc(final.id)} → {esc(final.assignee or '-')}"),
        row("run_forever (flat) ran a real engineer beat", beat_ran,
            final.latest_run.status if final.latest_run is not None else "-"),
        row("task reached done", done, final.status.value),
        row("build landed to company main", landed, f"greet.py present: {landed}"),
        row("status() (flat glance)", True,
            f"{len(status.employees)} employees · {status.open_tasks} open · {status.running_beats} running"),
    ])
    groups = "\n".join(
        row(f"{p.group} — {p.verb}", p.ok, p.detail) for p in probes
    )
    log = _git(company_main, "log", "--oneline", "-4") or "(no commits on company main yet)"
    verdict = "PASS ✅" if accepted else "INCOMPLETE ❌"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>spec 14 — the public facade (live)</title>
<style>
 html {{ background: #ffffff; }}
 body {{ font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; max-width: 860px; margin: 40px auto;
        color: #1c1c1c; background: #ffffff; padding: 0 20px; }}
 h1 {{ font-size: 24px; }} h2 {{ font-size: 18px; margin-top: 32px; }}
 table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
 td, th {{ border: 1px solid #e3e3df; padding: 7px 10px; text-align: left; vertical-align: top; }}
 th {{ background: #f6f5f2; }}
 code {{ background: #f6f5f2; padding: 1px 5px; border-radius: 4px; font-size: 13px; }}
 pre {{ background: #f6f5f2; padding: 12px 14px; border-radius: 6px; overflow-x: auto; }}
 .lead {{ color: #555; }} .verdict {{ font-weight: 700; }}
</style></head><body>
<h1>spec 14 — the public facade, live</h1>
<p class="lead"><code>from chorus import Chorus</code> → a two-tier kernel: <b>simple on top</b> (the flat
front door anyone can operate a company with) and <b>complete underneath</b> (every niche capability
under its group). The kernel stays dream-free; <code>chorus_harness</code> brings the model (Azure
{esc(deployment)}) and plugs into the two seams — execution (<code>runner_for</code>) and landing
(<code>landers</code>).</p>
<p class="verdict">Result: {verdict}</p>

<h2>High-level tier — the §0 front door (flat verbs)</h2>
<table><tr><th></th><th>step</th><th>evidence</th></tr>
{front}
</table>

<h2>Low-level tier — one verb per group</h2>
<p class="lead">Reached as <code>org.&lt;group&gt;.&lt;verb&gt;</code>; namespaced so they never clutter the
front door. Enum-typed arguments cross as enums (no stringly), fail-closed on unknown subjects.</p>
<table><tr><th></th><th>group · verb</th><th>evidence</th></tr>
{groups}
</table>

<h2>What the engineer beat landed (company main)</h2>
<pre><code>{esc(log)}</code></pre>

<p class="lead">decompose · submit_verdict · memory are on <b>neither</b> tier — they are the employee's
own faculties, exercised inside the beat, never on the operator surface. Generated
{esc(datetime.now().isoformat(timespec="seconds"))}.</p>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
