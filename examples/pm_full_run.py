"""Full PM run — watch Piper turn a goal into a grounded decision, gated by the floor.

Seeds a worktree, hires a PM, assigns a "decide what to build next" task, and ticks the kernel —
logging the whole lifecycle: role identity → isolated worktree → grounding-floor-gated beat → landed
``doc`` artifact. This is the Slice-0 PM in one run: brief + manifest → beat → plan.md → land.

The point of the run is the **grounding floor** (pm design doc §01/§09/§10): the beat only reaches
``done`` if ``plan.md`` states a ``## Decision`` *and* cites at least one source. A plausible,
evidence-free plan is refused — the deterministic DoD, not a reviewer's eye, enforces it.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/pm_full_run.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import asyncio
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
from chorus_employee.pm import PM_PLAN_DOC
from chorus_harness import EmployeeHarnessFactory

# --- The Arceus product context: a real "what to build next" decision for the PM ---
_ARCEUS_CONTEXT = """\
Company: Arceus (arceus.sh) — "Your AI company, running autonomously."
Current state: The core execution loop (plan → code → test → ship) works. Early users are technical
founders. The top complaint in support is that a run's progress is opaque — users can't see what the
agents are doing between "started" and "shipped", so they lose trust and check in constantly.
Candidate next bets: (a) live presence/activity indicators for a running org; (b) a second LLM
provider for redundancy; (c) a marketing site refresh.
Signals: support tickets mentioning "what is it doing / is it stuck" are the single largest tag this
month; provider outages have been rare; site traffic is healthy.
"""

_TASK = (
    "You are the product manager for Arceus (arceus.sh). Here is the product context:\n\n"
    + _ARCEUS_CONTEXT
    + "\nDecide what to build next and write the plan to plan.md in your worktree. Include a "
    "`## Decision` section that states your choice and why in one or two sentences, and cite at "
    "least one source for the evidence behind it (a URL, a `Source:` line, or a `[n]` reference — "
    "the support-ticket signal above is a citable source). Be decisive; this is a decision, not a "
    "list of open questions."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class LoggingBus(EventBus):
    """Print every beat event so the whole run_task loop is visible."""

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
    """Seed a minimal repo — the PM writes plan.md into its worktree, no starter code needed."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# Arceus product workspace\n", encoding="utf-8")
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


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-pm-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = SqliteLedger.open(":memory:")
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="arceus",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
        )
        ledger.employees.create(Employee(id="piper", name="Piper", role="pm"))

        # 1. WHO is being dispatched — the PM's role-faithful harness.
        cfg = role_beat_config(registry.get("pm").manifest)
        mat = factory.materialize(ledger.employees.get("piper"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("1. EMPLOYEE — materialized as its role (Product Manager, design doc §02)")
        _log("   employee : piper (pm)")
        _log(f"   tools    : {', '.join(cfg.tools)}")
        _log(f"   permission: {cfg.permission_mode}   memory: {cfg.memory_scope}")
        _log(f"   sandbox  : {cfg.sandbox}   isolation: {cfg.isolation}")
        _log(f"   worktree : {mat.working_dir}")
        _log("   branch   : chorus/piper")
        _log("   DoD      : grounding floor — plan.md must state a ## Decision AND cite a source")

        # 2. The task — decide what to build next for Arceus.
        ledger.tasks.submit(Task(id="arceus-next", intent=_TASK))
        assign_task(ledger, "arceus-next", "piper")
        _log("")
        _log("2. TASK assigned")
        _log("   arceus-next: Decide what to build next (presence vs provider vs site)")

        # 3. The kernel ticks — dispatch the beat.
        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
            roles=registry,
            landers=default_landers(factory.company_root),
            event_bus=LoggingBus(),
            max_concurrent_runs=1,
        )

        for n in range(1, 4):
            task = ledger.tasks.get("arceus-next")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log("")
            _log(f"3.{n} TICK — kernel dispatches the PM beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

            run = ledger.runs.for_task("arceus-next")[-1]
            dod = ledger.dod.get_for_task("arceus-next")
            _log(f"   run status: {run.status.value}   DoD: {dod.status.value if dod else '-'}")

        # 4. What the PM produced.
        wt = mat.working_dir
        _log("")
        _log("=" * 72)
        _log("4. RESULT")
        _log(f"   task status : {ledger.tasks.get('arceus-next').status.value}")  # type: ignore[union-attr]
        plan_file = wt / PM_PLAN_DOC
        if plan_file.exists():
            plan = plan_file.read_text(encoding="utf-8")
            _log(f"   plan.md ({len(plan)} chars):")
            _log("   " + "-" * 60)
            for line in plan.splitlines()[:40]:
                _log(f"   {line}")
            if len(plan.splitlines()) > 40:
                _log(f"   ... ({len(plan.splitlines()) - 40} more lines)")
            _log("   " + "-" * 60)
        else:
            _log("   ⚠ no plan.md in worktree")

        artifacts = ledger.artifacts.list_for_task("arceus-next")
        if artifacts:
            a = artifacts[0]
            _log(f"   ★ DOC ARTIFACT LANDED: type={a.type.value} ref={a.resource_ref}")
        else:
            _log("   no artifact landed yet (the grounding floor gates an ungrounded plan).")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
