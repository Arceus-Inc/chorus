"""M1 crash-safety, keyed end-to-end: kill a beat mid-run → the kernel reaps, re-dispatches, completes.

The M1 acceptance is "kill mid-run, restart, the lease-recovery pass re-dispatches; no stranded
sweeper needed." This proves it with a **real** dream beat:

1. Seed a repo, hire an Engineer, submit a task.
2. Inject the exact durable residue of a crash mid-beat — the task ``in_progress``, locked under a
   dead ``run`` whose lease has already passed.
3. Tick the real kernel. With no manual intervention it must: reap the orphan (release the locks,
   mark it ``timed_out``), recover the stranded task (enqueue a continuation wake), re-dispatch a
   fresh beat, pass the ``pytest && ruff`` DoD, and land the task ``done`` (PR merged).

Run keyed:  AZURE_OPENAI_API_KEY=… AZURE_OPENAI_BASE_URL=… AZURE_OPENAI_DEPLOYMENT=… \
            uv run python examples/crash_recovery_m1.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler
from chorus.ledger import RunStatus, SqliteLedger, Task, TaskStatus
from chorus.ledger._models import Run
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_TASK = (
    "In calc.py add a function subtract(a, b) that returns a - b. In test_calc.py add a test "
    "test_subtract asserting subtract(3, 1) == 2. Keep the existing add function and its test."
)


def _log(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    ).stdout.strip()


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


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-crash-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = SqliteLedger.open(":memory:")
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key, base_url=base_url, deployment=deployment,
            company_id="acme", roles=registry, pricing=default_pricing_from_env(), seed=seed,
        )
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))

        # 1. The task is already in_progress, locked under a DEAD run whose lease passed — exactly
        #    what a process that died mid-beat leaves behind. No wake: recovery must re-create it.
        dead_lease = datetime.now(UTC) - timedelta(seconds=300)
        ledger.tasks.submit(
            Task(
                id="t1", intent=_TASK, status=TaskStatus.IN_PROGRESS, assignee_employee_id="ada",
                checkout_run_id="run_dead", execution_run_id="run_dead",
            )
        )
        ledger.runs.create(
            Run(id="run_dead", employee_id="ada", task_id="t1", status=RunStatus.RUNNING,
                lease_expires_at=dead_lease)
        )
        _log("=" * 72)
        _log("1. CRASH INJECTED")
        _log(f"   task t1: status={ledger.tasks.get('t1').status.value} locked-by=run_dead")  # type: ignore[union-attr]
        _log(f"   run_dead: RUNNING, lease expired at {dead_lease.isoformat()} (the crash signature)")

        # 2. The real kernel — same factory/scheduler the tick uses.
        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory, budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry, landers=default_landers(factory.company_root),
            max_concurrent_runs=1,
        )

        _log("")
        _log("2. RECOVERY — tick the kernel (no manual intervention)")
        for n in range(1, 6):
            task = ledger.tasks.get("t1")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())
            dead = ledger.runs.get("run_dead")
            latest = ledger.runs.for_task("t1")[-1]
            _log(
                f"   tick {n}: run_dead={dead.status.value if dead else '?'}  "  # reaped → timed_out
                f"task={ledger.tasks.get('t1').status.value}  "  # type: ignore[union-attr]
                f"latest_run={latest.id[:12]}/{latest.status.value}"
            )

        # 3. What the recovery produced.
        wt = factory.company_root / "worktrees" / "ada"
        company_main = factory.company_root / "repo"
        dead = ledger.runs.get("run_dead")
        retry = next((r for r in ledger.runs.for_task("t1") if r.id != "run_dead"), None)
        _log("")
        _log("=" * 72)
        _log("3. RESULT")
        _log(f"   run_dead reaped : {dead.status.value if dead else '?'}  (expect timed_out)")
        _log(f"   retry run       : {retry.id[:12] if retry else None}/{retry.status.value if retry else '-'}")
        _log(f"   task status     : {ledger.tasks.get('t1').status.value}")  # type: ignore[union-attr]
        _log(f"   worktree subtract(): {'subtract' in (wt / 'calc.py').read_text(encoding='utf-8') if (wt / 'calc.py').exists() else False}")
        _log(f"   company main log:\n{_git(company_main, 'log', '--oneline', '-3')}")
        artifacts = ledger.artifacts.list_for_task("t1")
        if artifacts and ledger.tasks.get("t1").status is TaskStatus.DONE:  # type: ignore[union-attr]
            _log("   ★ CRASH RECOVERED: orphan reaped → re-dispatched → DoD green → PR merged → done.")
        else:
            _log("   recovery did not complete — inspect the tick log above.")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
