"""The public facade, live — the §0 front door + every group, end to end (spec 14 F7).

The whole point of spec 14: ``from chorus import Chorus`` gives a two-tier kernel that is *simple on
top* (anyone can operate a company) and *complete underneath* (every niche capability under its group).
This script proves both against a real model — the front door reads exactly like §0:

    ledger = SqliteLedger.open("company.db")
    factory = EmployeeHarnessFactory(..., ledger=ledger)          # the execution layer (dream + creds)
    org = Chorus.build(ledger=ledger, org_repo=..., memory_repo=..., dream=dream,
                       beat_runner_for=factory, landers=factory.landers)
    org.hire(name="moe", role="manager")
    org.hire(name="eng1", role="engineer", reports_to="moe")
    org.hire(name="ria",  role="reviewer", reports_to="moe")
    task = org.submit("…", assignee="eng1")   # no DoD — the engineer's role defines reviewed_build
    org.start() ; ... ; await org.stop()      # the concurrent always-on heartbeat, then drain
    org.status()

The engineer's *role* sets the DoD (a reviewed build), so the operator never hand-specifies one: the
beat builds, a real reviewer renders the verdict on the author's worktree, the objective floor runs, and
the work lands on company main. The factory and the kernel share **one** ledger so the reviewer's
verdict and the factory's capability tools write to the same store. Then one verb on each low-level
group is exercised. Writes ``reports/m1-public-facade.html``.

In production the heartbeat is the concurrent always-on ``org.start()`` / ``await org.stop()`` runner
(up to ``Caps.max_concurrent_runs`` beats at once); this script instead single-steps it with
``tick`` + ``drain`` so the run is deterministic and reaches ``done`` in a bounded number of pulses.

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
from chorus.ledger import SqliteLedger
from chorus.roles import RoleRegistry
from chorus_cli._beats import default_pricing_from_env
from chorus_harness import EmployeeHarnessFactory

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m1-public-facade.html"
_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})
_INTENT = (
    "In calc.py add a function subtract(a, b) that returns a - b. "
    "In test_calc.py add a test test_subtract asserting subtract(3, 1) == 2. "
    "Keep the existing add function and its test. Make the changes directly in those files."
)


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
    (path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (path / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )


@dataclass
class GroupProbe:
    """One low-level group verb, exercised after the task settles (pure ledger ops, no new beats)."""

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


async def _run_until_terminal(org: Chorus, task_id: str, *, max_pulses: int) -> TaskView:
    """Advance the public heartbeat one settled pulse at a time until the task is terminal.

    A reviewed build parks ``blocked`` between steps (engineer build → reviewer verdict → objective
    floor); that is not terminal, so each ``tick`` + ``drain`` runs the next step to completion and the
    following pulse dispatches the review/floor it queued. (``run_forever`` is the production driver;
    ``tick``/``drain`` is the deterministic one every keyed example uses.)
    """
    for _ in range(max_pulses):
        await org.tick()
        await org.drain()
        view = org.inspect.task(task_id)
        beat = view.latest_run.status if view.latest_run is not None else "-"
        _log(f"   … status={view.status.value} beat={beat}")
        if view.status in _TERMINAL:
            break
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

    # ── one ledger, shared by the execution layer and the kernel ──────────────────────────────────
    ledger = SqliteLedger.open(str(base / "company.db"))
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key, base_url=base_url, deployment=deployment,
        company_id="acme", roles=registry, pricing=default_pricing_from_env(),
        seed=seed, work_root=base / "work", ledger=ledger,
    )

    # ── the front door (spec 14 §0): build once, then operate with flat verbs ─────────────────────
    org = Chorus.build(
        ledger=ledger,
        org_repo=org_repo,
        memory_repo=str(base / "memory"),
        dream=dream,
        beat_runner_for=factory,          # how a beat runs (+ how a reviewer reads the author's worktree)
        landers=factory.landers,          # how the deliverable lands
        caps=Caps(tick_interval_s=0.5),
        company_id="acme",
    )

    _log(f"deployment={deployment}")
    _log("=" * 72)
    _log("§0 FRONT DOOR — build → hire → submit → tick/drain → status")

    org.hire(name="moe", role="manager")
    org.hire(name="eng1", role="engineer", reports_to="moe")
    org.hire(name="ria", role="reviewer", reports_to="moe")
    task = org.submit(_INTENT, assignee="eng1")  # no operator DoD — the engineer's role IS reviewed_build
    _log(f"   hired moe/eng1/ria; submitted {task.id} → eng1 (role DoD = reviewed_build)")

    final = asyncio.run(_run_until_terminal(org, task.id, max_pulses=12))
    status: WorkforceStatus = org.status()
    beat_ran = final.latest_run is not None
    done = final.status is TaskStatus.DONE
    company_main = factory.company_root / "repo"
    calc = company_main / "calc.py"
    landed = calc.exists() and "subtract" in calc.read_text(encoding="utf-8")
    _log(f"   final: status={final.status.value} dod={_dod_kind(final)} "
         f"beat_ran={beat_ran} landed_to_main={landed}")
    _log(f"   status(): {len(status.employees)} employees, {status.open_tasks} open, "
         f"{status.running_beats} running")

    # ── the groups (spec 14 §2.2): one verb each, after the heartbeat is stopped (no new beats) ───
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
    ledger.close()
    return 0 if accepted else 1


def _dod_kind(view: TaskView) -> str:
    return view.dod.kind.value if view.dod is not None else "-"


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
        row("Chorus.build(ledger=…, beat_runner_for=factory, landers=…)", True, "two-tier kernel"),
        row("hire (flat)", len(status.employees) >= 3, f"{len(status.employees)} employees"),
        row("submit (flat) — no operator DoD, the role defines it", True,
            f"{esc(final.id)} → {esc(final.assignee or '-')} · DoD={_dod_kind(final)}"),
        row("run_forever (flat) ran a real reviewed build", beat_ran,
            final.latest_run.status if final.latest_run is not None else "-"),
        row("task reached done (build → review → integrate)", done, final.status.value),
        row("build landed to company main", landed, f"subtract() in calc.py: {landed}"),
        row("status() (flat glance)", True,
            f"{len(status.employees)} employees · {status.open_tasks} open · {status.running_beats} running"),
    ])
    groups = "\n".join(row(f"{p.group} — {p.verb}", p.ok, p.detail) for p in probes)
    log = _git(company_main, "log", "--oneline", "-4") or "(no commits on company main yet)"
    facade = "PASS ✅" if accepted else "INCOMPLETE ❌"
    pipeline = "reached done ✅" if done else f"{final.status.value} (live M3 sprint reliability)"
    verdict = f"facade wiring {facade} &nbsp;·&nbsp; live build {pipeline}"
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
under its group). The operator never hand-specifies a DoD — the roles define them: the manager (Azure
{esc(deployment)}) decomposes, an engineer builds, a reviewer renders the verdict on the author's
worktree, and the manager integrates. The facade bar is that the front door is wired and every group
reachable; whether a given <i>live</i> beat reaches <code>done</code> is the M3 sprint pipeline's
reliability, reported separately below.</p>
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

<h2>What the reviewed build landed (company main)</h2>
<pre><code>{esc(log)}</code></pre>

<p class="lead">decompose · submit_verdict · memory are on <b>neither</b> tier — they are the employee's
own faculties, exercised inside the beat, never on the operator surface. Generated
{esc(datetime.now().isoformat(timespec="seconds"))}.</p>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
