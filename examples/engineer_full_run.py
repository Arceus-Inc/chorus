"""Full engineer run, instrumented — watch a real engineer ship a PR end to end.

Seeds a tiny repo, hires an engineer, assigns a task, and ticks the kernel — logging *everything*:
the role-faithful harness it materializes, every beat event (planner → generator → evaluator, tool
calls), the DoD verdict, and the PR artifact it lands. This is the whole spec-06 Engineer in one run:
role identity → isolated worktree → DoD-gated beat → landed outcome.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/engineer_full_run.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.roles import RoleRegistry, default_roles, role_beat_config
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_TASK = (
    "In calc.py add a function subtract(a, b) that returns a - b. "
    "In test_calc.py add a test test_subtract asserting subtract(3, 1) == 2. "
    "Keep the existing add function and its test. Make the changes directly in those files."
)


_LOGFILE: object | None = None  # a file handle set in main(); _log flushes to it + stdout


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()
    if _LOGFILE is not None:
        _LOGFILE.write(msg + "\n")  # type: ignore[attr-defined]
        _LOGFILE.flush()  # type: ignore[attr-defined]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


class LoggingBus(EventBus):
    """An EventBus that prints every beat event, so the whole run_task loop is visible.

    Streamed prose (RUN_TEXT) arrives token-by-token; we buffer it and print whole lines so the
    planner/generator reasoning is readable instead of one-token-per-line.
    """

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self._buf = ""

    def _flush_prose(self) -> None:
        line = self._buf.strip()
        self._buf = ""
        if line:
            _log(f"    · {line[:200]}")

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TEXT:
            self._buf += str(p.get("text", ""))
            while "\n" in self._buf:
                head, self._buf = self._buf.split("\n", 1)
                if head.strip():
                    _log(f"    · {head.strip()[:200]}")
            return
        self._flush_prose()
        if event.kind is EventKind.RUN_TOOL_USE:
            _log(f"    → TOOL {p.get('tool', '?')}  {str(p.get('input', ''))[:160]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tag = "ERR" if p.get("is_error") else "ok"
            note = f"  {str(p.get('content', ''))[:160]}" if p.get("is_error") else ""
            _log(f"    ← {p.get('tool', '?')} [{tag}]{note}")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⊢ evaluated: {p.get('outcome', p)}")
        elif event.kind is EventKind.RUN_STARTED:
            _log("    ▸ beat started")
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")


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

    base = Path(tempfile.mkdtemp(prefix="chorus-engineer-"))
    os.chdir(base)
    global _LOGFILE
    log_path = os.environ.get("CHORUS_RUN_LOG")
    if log_path:
        _LOGFILE = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 (closed at process exit)
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

        # 1. WHO is being dispatched — the role-faithful harness the kernel will materialize.
        cfg = role_beat_config(registry.get("engineer").manifest)
        mat = factory.materialize(ledger.employees.get("ada"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("1. EMPLOYEE — materialized as its role (spec 06 §2)")
        _log("   employee : ada (engineer)")
        _log(f"   tools    : {', '.join(cfg.tools)}")
        _log(f"   permission: {cfg.permission_mode}   memory: {cfg.memory_scope}")
        _log(f"   worktree : {mat.working_dir}")
        _log(f"   branch   : chorus/ada   (seeded from {seed.name})")
        _log(f"   DoD      : {cfg.tools and 'pytest -q && ruff check .'} (CI gate, auto-applied at intake)")
        _log(f"   seeded   : {_git(mat.working_dir, 'ls-files')!r}")

        # 2. The task.
        ledger.tasks.submit(Task(id="t1", intent=_TASK))
        assign_task(ledger, "t1", "ada")
        _log("")
        _log("2. TASK assigned")
        _log(f"   t1: {_TASK}")

        # 3. The kernel ticks — dispatch the beat, watch the run_task loop.
        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory, budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry, landers=default_landers(factory.company_root),
            event_bus=LoggingBus(), max_concurrent_runs=1,
        )
        import asyncio

        for n in range(1, 4):  # up to 3 ticks (self-repair retries on a failed DoD)
            task = ledger.tasks.get("t1")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log("")
            _log(f"3.{n} TICK — kernel dispatches the engineer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

            run = ledger.runs.for_task("t1")[-1]
            dod = ledger.dod.get_for_task("t1")
            _log(f"   run status: {run.status.value}   DoD: {dod.status.value if dod else '-'}")
            _log(f"   run outcome: {run.outcome}")  # for an errored beat this carries phase + error

        # 4. What the engineer produced + what landed.
        wt = mat.working_dir
        _log("")
        _log("=" * 72)
        _log("4. RESULT")
        _log(f"   task status : {ledger.tasks.get('t1').status.value}")  # type: ignore[union-attr]
        _log(f"   worktree git log:\n{_git(wt, 'log', '--oneline')}")
        _log(f"   diff vs seed:\n{_git(wt, 'diff', 'HEAD~1', '--stat') or '(no committed change)'}")
        _log("   calc.py now:")
        calc = (wt / "calc.py").read_text(encoding="utf-8") if (wt / "calc.py").exists() else ""
        for line in calc.splitlines():
            _log(f"     {line}")

        artifacts = ledger.artifacts.list_for_task("t1")
        _log("")
        if artifacts:
            a = artifacts[0]
            _log(f"   ★ PR ARTIFACT LANDED: type={a.type.value} ref={a.resource_ref}")
            # PR → CI → merge: the deliverable is now integrated into the company main, so the next
            # employee branches off the shipped work.
            company_main = factory.company_root / "repo"
            _log(f"   company main log:\n{_git(company_main, 'log', '--oneline', '-3')}")
            integrated = "subtract" in (company_main / "calc.py").read_text(encoding="utf-8")
            _log(f"   company main has subtract(): {integrated}")
            _log("   → the engineer shipped: DoD green (pytest+ruff) → PR recorded → merged to main.")
        else:
            _log("   no artifact landed (DoD not green this run — see run/DoD status above).")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
