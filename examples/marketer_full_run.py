"""Full marketer run — watch Mira draft a content piece for Arceus end to end.

Seeds a worktree, hires a marketer, assigns a content task about Arceus (arceus.sh —
"Your AI company, running autonomously"), and ticks the kernel — logging the complete
lifecycle: role identity → isolated worktree → DoD-gated beat → landed content artifact.

This is the Slice 0 Marketer in one run: brief + manifest → beat → content draft → land.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/marketer_full_run.py

Skips cleanly (exit 0) when those env vars are unset.
"""

from __future__ import annotations

import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import subprocess
import sys
import tempfile
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.roles import RoleRegistry, default_roles, role_beat_config
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_employee.marketer import MARKETER_CONTENT_DOC
from chorus_harness import EmployeeHarnessFactory

# --- The Arceus brief: real company content for the marketer to work with ---
_ARCEUS_CONTEXT = """\
Company: Arceus (arceus.sh)
Tagline: Your AI company, running autonomously.
What it is: An AI company operating system. Arceus boots a team of LLM agents that plan \
sprints, write code, run QA, and ship — while you act as the board of directors.
Value prop: From goal to shipped. Stop managing sprints. Start steering outcomes. Arceus \
runs the entire execution loop — planning, coding, testing, shipping — so you never have to.
How it works: (1) Define your goal in plain language. (2) CEO agent plans the sprint. \
(3) Team builds & ships (Developer, Tester, Designer in a heartbeat loop). (4) You govern — \
review decisions, approve proposals, steer direction.
Key features: Autonomous Agents (CEO, CTO, PM, Developer, Tester, Designer — 8 agents in a \
heartbeat loop), Hippocampus Memory (4-tier: static, dynamic, procedural, priming), \
Human Governance (you're the board, not the operator), Adaptive Intelligence (pattern \
detection → habit formation → skill evolution).
Target audience: Technical founders who move fast and want to ship without managing a team.
"""

_TASK = (
    "You are writing content for Arceus (arceus.sh). Here is the company context:\n\n"
    + _ARCEUS_CONTEXT
    + "\nWrite a blog post titled 'Why We Built Arceus' explaining the problem (managing "
    "sprints is overhead for founders), the insight (LLM agents can run the execution loop), "
    "and the solution (Arceus as an AI company OS). Keep it under 800 words, on-brand "
    "(technical, direct, no hype), and structured for SEO + AI-citation readiness. "
    "Write the output to content_draft.md in your worktree."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    ).stdout.rstrip()


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
    """Seed a minimal repo — the marketer writes into it, but doesn't need starter code."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# Arceus content workspace\n", encoding="utf-8")
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

    base = Path(tempfile.mkdtemp(prefix="chorus-marketer-"))
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
            company_id="arceus",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))

        # 1. WHO is being dispatched — the marketer's role-faithful harness.
        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("1. EMPLOYEE — materialized as its role (Marketer, design doc §02)")
        _log("   employee : mira (marketer)")
        _log(f"   tools    : {', '.join(cfg.tools)}")
        _log(f"   permission: {cfg.permission_mode}   memory: {cfg.memory_scope}")
        _log(f"   sandbox  : {cfg.sandbox}   isolation: {cfg.isolation}")
        _log(f"   worktree : {mat.working_dir}")
        _log("   branch   : chorus/mira")

        # 2. The task — write content about Arceus.
        ledger.tasks.submit(Task(id="arceus-blog", intent=_TASK))
        assign_task(ledger, "arceus-blog", "mira")
        _log("")
        _log("2. TASK assigned")
        _log("   arceus-blog: Write 'Why We Built Arceus' blog post")

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
        import asyncio

        for n in range(1, 4):
            task = ledger.tasks.get("arceus-blog")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log("")
            _log(f"3.{n} TICK — kernel dispatches the marketer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

            run = ledger.runs.for_task("arceus-blog")[-1]
            dod = ledger.dod.get_for_task("arceus-blog")
            _log(f"   run status: {run.status.value}   DoD: {dod.status.value if dod else '-'}")

        # 4. What the marketer produced.
        wt = mat.working_dir
        _log("")
        _log("=" * 72)
        _log("4. RESULT")
        _log(f"   task status : {ledger.tasks.get('arceus-blog').status.value}")  # type: ignore[union-attr]
        content_file = wt / MARKETER_CONTENT_DOC
        if content_file.exists():
            content = content_file.read_text(encoding="utf-8")
            _log(f"   content_draft.md ({len(content)} chars):")
            _log("   " + "-" * 60)
            for line in content.splitlines()[:30]:
                _log(f"   {line}")
            if len(content.splitlines()) > 30:
                _log(f"   ... ({len(content.splitlines()) - 30} more lines)")
            _log("   " + "-" * 60)
        else:
            _log("   ⚠ no content_draft.md in worktree")

        artifacts = ledger.artifacts.list_for_task("arceus-blog")
        if artifacts:
            a = artifacts[0]
            _log(f"   ★ CONTENT ARTIFACT LANDED: type={a.type.value} ref={a.resource_ref}")
        else:
            _log("   no artifact landed yet (see run/DoD status above).")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
