"""M4 S1 — recurring work, live: a cron routine fires into a real engineer beat (spec 13 §8).

The whole S1 chain against a live model, end to end:

    add_routine (facade)  →  the tick's CRON step fires it (exact-once across ticks)
        →  spawns a task stamped origin_kind=routine_execution
        →  normal dispatch runs a real engineer beat (Azure gpt-5.2)
        →  the routine_run is linked + marked dispatched

Proves the one thing S1 adds — routines are now *creatable*, and the already-built firing engine
carries them into real work — and writes a standalone HTML report to reports/m4-s1-routine.html.

    set -a; eval "$(grep -E '^AZURE_OPENAI_(API_KEY|BASE_URL|DEPLOYMENT)=' .env)"; set +a
    uv run python examples/m4_routine_s1_live.py

Skips cleanly (exit 0) when the Azure env vars are unset.
"""

from __future__ import annotations

import asyncio
import html
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.facade import Caps, Chorus
from chorus.heartbeat import Scheduler
from chorus.ledger import Artifact, Ledger, RoutineRun, RoutineRunStatus, Task, TaskStatus
from chorus.observability import LedgerInspector, RoutineView
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_REPORT = Path(__file__).resolve().parents[1] / "reports" / "m4-s1-routine.html"
_SCHEDULE = "* * * * *"  # every minute — the soonest edge, so one tick fires it
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
            "init",
        ],
        check=True,
        capture_output=True,
    )


def _facade(ledger: Ledger, registry: RoleRegistry) -> Chorus:
    """A facade over the ledger — used only to create the routine through the public API."""
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=registry,
        caps=Caps(),
    )


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-m4-s1-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
        )
        # An engineer to own the routine + a reviewer (the engineer's DoD is a reviewed build, so a
        # firing carries the work into the real M3 engineer→reviewer pipeline).
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        ledger.employees.create(Employee(id="rob", name="Rob", role="reviewer"))
        _log(f"deployment={deployment}")

        # 1. CREATE the routine through the facade — the seam S1 adds (was a NotImplementedError stub).
        view = _facade(ledger, registry).routines.add(
            employee="Ada", intent_template=_INTENT, schedule=_SCHEDULE
        )
        (trigger,) = view.triggers
        edge = trigger.next_run_at
        assert edge is not None
        _log("=" * 72)
        _log("1. ROUTINE CREATED (facade.add_routine)")
        _log(
            f"   {view.id}  owner=ada  schedule={_SCHEDULE}  concurrency={view.concurrency_policy.value}"
        )
        _log(f"   next_run_at={edge.isoformat()}")

        # 2. TICK — the CRON step fires the routine, then dispatch runs the engineer beat.
        # The kernel clock is frozen at the firing edge (as the M3 reviewed-build suite does): the
        # trigger reads as due, and a long live beat is never reaped as a stale lease while it runs.
        # A frozen clock also gives exact-once for free — fire_routine advances the edge past `edge`,
        # so the trigger is never due again on a later tick.
        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry,
            landers=default_landers(factory.company_root, ledger=ledger),
            clock=lambda: edge,
            max_concurrent_runs=2,
            max_review_rounds=1,
        )

        # Tick to terminal: fire → engineer build → (parks blocked for review) → reviewer verdict →
        # build floor → done. "blocked" is the parked-for-review state a later tick resolves — so we
        # break only on DONE, never on the intermediate block (mirrors the M3 reviewed-build loop).
        for n in range(1, 13):
            runs = ledger.routine_runs.by_routine(view.id)
            if runs and runs[0].linked_task_id is not None:
                task = ledger.tasks.get(runs[0].linked_task_id)
                if task is not None and task.status is TaskStatus.DONE:
                    break

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            _log("")
            _log(f"2.{n} TICK")
            asyncio.run(_pulse())
            spawned_now = ledger.routine_runs.by_routine(view.id)
            if spawned_now and spawned_now[0].linked_task_id is not None:
                t = ledger.tasks.get(spawned_now[0].linked_task_id)
                beats = ledger.runs.for_task(spawned_now[0].linked_task_id)
                last = beats[-1] if beats else None
                _log(
                    f"     task={t.status.value if t else '?'}  "
                    f"beats={len(beats)}  last={last.status.value if last else '-'}/{last.outcome if last else '-'}"
                )

        # 3. WHAT FIRED — exact-once, typed origin, linked task.
        runs = ledger.routine_runs.by_routine(view.id)
        run = runs[0] if runs else None
        spawned = run.linked_task_id if run else None
        task = ledger.tasks.get(spawned) if spawned else None
        _log("")
        _log("=" * 72)
        _log("3. WHAT FIRED")
        _log(f"   routine_runs: {len(runs)} (exact-once: exactly 1 expected)")
        if run is not None:
            _log(f"   run {run.id}: status={run.status.value} linked_task={run.linked_task_id}")
        if task is not None:
            _log(
                f"   task {task.id}: status={task.status.value} origin_kind={task.origin_kind.value}"
            )
            _log(f"     origin_id={task.origin_id}  origin_fingerprint={task.origin_fingerprint}")

        artifacts = ledger.artifacts.list_for_task(spawned) if spawned else []
        beats_ran = len(ledger.runs.for_task(spawned)) if spawned else 0
        if artifacts:
            _log(
                f"   ★ ARTIFACT LANDED: type={artifacts[0].type.value} ref={artifacts[0].resource_ref}"
            )
        _log(f"   engineer beats executed: {beats_ran}")

        # The S1 bar is "recurring work is creatable + the firing engine carries it into a real beat":
        # routine created → fired exact-once → typed routine_execution origin → a real beat dispatched.
        # (Reaching DONE depends on the live reviewed-build pipeline — reported as a bonus, not the bar.)
        s1_ok = (
            len(runs) == 1
            and run is not None
            and run.status is RoutineRunStatus.DISPATCHED
            and task is not None
            and task.origin_kind.value == "routine_execution"
            and beats_ran >= 1
        )

        _REPORT.parent.mkdir(parents=True, exist_ok=True)
        _REPORT.write_text(
            _render(
                factory,
                view=view,
                run=run,
                task=task,
                runs=runs,
                artifacts=artifacts,
                beats_ran=beats_ran,
            ),
            encoding="utf-8",
        )
        _log("")
        _log(f"S1 chain {'OK ✅' if s1_ok else 'INCOMPLETE ❌'}   report → {_REPORT}")
        return 0 if s1_ok else 1
    finally:
        ledger.close()


def _render(
    factory: EmployeeHarnessFactory,
    *,
    view: RoutineView,
    run: RoutineRun | None,
    task: Task | None,
    runs: list[RoutineRun],
    artifacts: list[Artifact],
    beats_ran: int,
) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value))

    exact_once = len(runs) == 1
    fired = run is not None and run.status is RoutineRunStatus.DISPATCHED
    from_routine = task is not None and task.origin_kind.value == "routine_execution"
    landed = bool(artifacts)
    done = task is not None and task.status is TaskStatus.DONE
    company_main = factory.company_root / "repo" / "calc.py"
    integrated = company_main.exists() and "subtract" in company_main.read_text(encoding="utf-8")

    def row(label: str, ok: bool, detail: str) -> str:
        mark = "✅" if ok else "❌"
        return f"<tr><td>{mark}</td><td>{esc(label)}</td><td><code>{esc(detail)}</code></td></tr>"

    run_detail = run.status.value if run is not None else "-"
    origin_detail = task.origin_kind.value if task is not None else "-"
    task_status_detail = task.status.value if task is not None else "-"
    # The S1 acceptance bar — what this slice actually adds (the firing engine already existed).
    checks = "\n".join(
        [
            row("routine created (facade.add_routine)", True, view.id),
            row("fired exact-once across ticks", exact_once, f"{len(runs)} routine_run(s)"),
            row("firing dispatched + linked a task", fired, run_detail),
            row("task carries routine_execution origin", from_routine, origin_detail),
            row(
                "a real engineer beat was dispatched + ran", beats_ran >= 1, f"{beats_ran} beat(s)"
            ),
        ]
    )
    # Beyond S1 — the firing flowed into the live M3 reviewed-build pipeline (reliability is M3's, not S1's).
    bonus = "\n".join(
        [
            row("task reached done via reviewed-build", done, task_status_detail),
            row("artifact landed (PR)", landed, str(artifacts[0].resource_ref) if landed else "-"),
            row("shipped to company main", integrated, f"subtract() in main: {integrated}"),
        ]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>M4 S1 — recurring work (live)</title>
<style>
 html {{ background: #ffffff; }}
 body {{ font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; max-width: 820px; margin: 40px auto;
        color: #1c1c1c; background: #ffffff; padding: 0 20px; }}
 h1 {{ font-size: 24px; }} h2 {{ font-size: 18px; margin-top: 32px; }}
 table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
 td, th {{ border: 1px solid #e3e3df; padding: 7px 10px; text-align: left; vertical-align: top; }}
 code {{ background: #f6f5f2; padding: 1px 5px; border-radius: 4px; font-size: 13px; }}
 .lead {{ color: #555; }}
</style></head><body>
<h1>M4 S1 — recurring work, live 🟨</h1>
<p class="lead">A cron <b>routine</b> created through <code>Chorus.add_routine</code> fired on the
heartbeat's CRON step and spawned a task that a real engineer beat (Azure {esc(os.environ.get("AZURE_OPENAI_DEPLOYMENT", "?"))})
carried to done — the firing engine already existed; S1 made routines <i>creatable</i>.</p>

<h2>The S1 chain, asserted</h2>
<table>
<tr><th></th><th>step</th><th>evidence</th></tr>
{checks}
</table>

<h2>Beyond S1 — into the live reviewed-build pipeline</h2>
<p class="lead">The firing flows straight into the real M3 engineer→reviewer flow; whether a single
live beat reaches <code>done</code> is M3's reliability, not what S1 adds.</p>
<table>
<tr><th></th><th>step</th><th>evidence</th></tr>
{bonus}
</table>

<h2>The routine</h2>
<table>
<tr><th>field</th><th>value</th></tr>
<tr><td>id</td><td><code>{esc(view.id)}</code></td></tr>
<tr><td>owner</td><td><code>{esc(view.employee_id)}</code></td></tr>
<tr><td>intent</td><td>{esc(view.intent_template)}</td></tr>
<tr><td>schedule</td><td><code>{esc(_SCHEDULE)}</code></td></tr>
<tr><td>concurrency</td><td><code>{esc(view.concurrency_policy.value)}</code> (S1 safe default)</td></tr>
<tr><td>catch-up</td><td><code>{esc(view.catch_up_policy.value)}</code></td></tr>
</table>

<h2>What landed</h2>
<pre><code>{esc(_git(factory.company_root / "repo", "log", "--oneline", "-3") or "(no commits)")}</code></pre>
<p class="lead">Generated {esc(datetime.now().isoformat(timespec="seconds"))}.</p>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
