"""PM + Researcher — the depth-2 chain, live: Piper → researcher → web_research.

Proves the PM's Tier-1 evidence specialist end to end, keyed:
  1. Piper spawns the ``researcher`` subagent to gather cited evidence (depth-1).
  2. The researcher ITSELF spawns the shared ``web_research`` orchestrator for real market facts
     (depth-2) — so no claim is written from memory.
  3. The researcher writes ``research_brief.md`` + returns a typed ResearchBrief; Piper cites its
     ``source_url``\\ s in ``plan.md``'s ``## Decision`` — which is what clears the grounding floor.

The bus captures every ``SUBAGENT_SPAWNED`` so we can assert BOTH ``researcher`` and ``web_research``
fired — the second only possible because the researcher inherited a scoped spawn set (§06 depth-2).

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... \
    TAVILY_API_KEY=... uv run python examples/pm_researcher_run.py

Skips cleanly (exit 0) when the Azure or Tavily env vars are unset.
"""

from __future__ import annotations

import asyncio
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
from chorus_employee.pm import PM_PLAN_DOC
from chorus_harness import EmployeeHarnessFactory

_ARCEUS_CONTEXT = """\
Company: Arceus (arceus.sh) — "Your AI company, running autonomously."
Current state: The core execution loop (plan → code → test → ship) works. The top support complaint is
that a run's progress is opaque — users can't see what the agents are doing between "started" and
"shipped", so they lose trust and check in constantly.
Candidate next bets: (a) live presence/activity indicators; (b) a second LLM provider; (c) a site refresh.
"""

_TASK = (
    "You are the product manager for Arceus (arceus.sh). Product context:\n\n"
    + _ARCEUS_CONTEXT
    + "\nDecide what to build next and write the plan to plan.md. This decision needs EXTERNAL "
    "evidence, so gather it first with your Researcher: "
    'call spawn_subagent(name="researcher", prompt="How do autonomous-agent / long-running-workflow '
    "products surface run progress and build user trust? Find real, current sources (e.g. how Temporal "
    'or agent platforms expose execution state) and cite them."). The researcher will run web_research '
    "itself and hand back a cited brief. Then write plan.md with a `## Decision` section stating your "
    "choice and why, citing the researcher's source URLs. Be decisive."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _DepthCaptureBus(EventBus):
    """Print the beat's events; record every subagent spawn to prove the depth-2 chain."""

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.spawned: list[str] = []
        self.completed: list[tuple[str, bool]] = []

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            tool = str(p.get("tool", "?"))
            inp = str(p.get("input", ""))[:150]
            if tool == "spawn_subagent":
                _log(f"    🔀 spawn_subagent  {inp}")
            elif tool in ("web_search", "web_extract"):
                _log(f"    🔎 {tool}  {inp[:120]}")
            elif tool == "write_file":
                _log(f"    ✍ write_file  {inp[:100]}")
        elif event.kind is EventKind.SUBAGENT_SPAWNED:
            name = str(p.get("subagent_name", "?"))
            self.spawned.append(name)
            depth = p.get("depth", "?")
            _log(f"    🔀 SUBAGENT_SPAWNED {name} (depth={depth})")
        elif event.kind is EventKind.SUBAGENT_COMPLETED:
            name = str(p.get("subagent_name", "?"))
            ok = bool(p.get("success", True)) and not p.get("is_error")
            self.completed.append((name, ok))
            _log(f"    ✅ {name} completed [{'ok' if ok else 'ERR'}]")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⚖ evaluated: passed={p.get('passed')}")
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
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
    tavily = os.environ.get("TAVILY_API_KEY") or os.environ.get("DREAM_TAVILY_API_KEY")
    if not (api_key and base_url and deployment and tavily):
        _log("skipping: set AZURE_OPENAI_* and TAVILY_API_KEY")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-pm-researcher-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    bus = _DepthCaptureBus()
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
            ledger=ledger,
        )
        ledger.employees.create(Employee(id="piper", name="Piper", role="pm"))
        cfg = role_beat_config(registry.get("pm").manifest)
        mat = factory.materialize(ledger.employees.get("piper"))  # type: ignore[arg-type]
        researcher = next((s for s in cfg.subagents if s.name == "researcher"), None)

        _log("=" * 72)
        _log("PM + RESEARCHER — depth-2 chain: Piper → researcher → web_research")
        _log("=" * 72)
        _log(f"   subagents on Piper   : {[s.name for s in cfg.subagents]}")
        _log(
            f"   researcher spawnable : "
            f"{[c.name for c in researcher.spawnable] if researcher else '?'}"
        )
        _log(f"   worktree : {mat.working_dir}")

        ledger.tasks.submit(Task(id="arceus-next", intent=_TASK))
        assign_task(ledger, "arceus-next", "piper")
        _log("\nTASK: gather evidence (researcher → web_research), then decide\n" + "-" * 72)

        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
            roles=registry,
            landers=default_landers(factory.company_root),
            event_bus=bus,
            max_concurrent_runs=1,
            lease_ttl_s=1200.0,
        )

        for n in range(1, 4):
            task = ledger.tasks.get("arceus-next")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\n[tick {n}] kernel dispatches the PM beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())
            run = ledger.runs.for_task("arceus-next")[-1]
            dod = ledger.dod.get_for_task("arceus-next")
            _log(f"   run: {run.status.value}   DoD: {dod.status.value if dod else '-'}")

        _log("\n" + "=" * 72)
        _log("RESULT")
        _log(f"   task status          : {ledger.tasks.get('arceus-next').status.value}")  # type: ignore[union-attr]
        _log(f"   subagents spawned    : {bus.spawned}")
        _log(f"   subagents completed  : {bus.completed}")
        depth2 = "researcher" in bus.spawned and "web_research" in bus.spawned
        _log(f"   ★ DEPTH-2 PROVEN     : {depth2}  (both researcher AND web_research fired)")

        wt = mat.working_dir
        for name in ("research_brief.md", PM_PLAN_DOC):
            f = wt / name
            if f.exists():
                body = f.read_text(encoding="utf-8")
                _log(f"\n   {name} ({len(body)} chars):\n   " + "-" * 60)
                for line in body.splitlines()[:24]:
                    _log(f"   {line}")
                _log("   " + "-" * 60)

        artifacts = ledger.artifacts.list_for_task("arceus-next")
        if artifacts:
            _log(f"\n   ★ DOC ARTIFACT LANDED: ref={artifacts[0].resource_ref}")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
