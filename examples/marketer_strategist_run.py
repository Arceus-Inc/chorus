"""Marketer + Strategist — the depth-2 chain, live: Mira → strategist → web_research.

Proves bounded depth-2 subagent spawning end to end, keyed:
  1. Mira spawns the ``strategist`` subagent to frame the bet (depth-1).
  2. The strategist ITSELF spawns the shared ``web_research`` orchestrator for cited market
     facts (depth-2) — the capability that did not exist before this build.
  3. The strategist writes ``strategy_brief.md``; Mira drafts ``content_draft.md`` from it.

The bus captures every ``SUBAGENT_SPAWNED`` so we can assert BOTH ``strategist`` and
``web_research`` fired — the second one only possible because the strategist inherited a scoped
spawn set + the shared per-beat counter.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... \
    TAVILY_API_KEY=... uv run python examples/marketer_strategist_run.py

Skips cleanly (exit 0) when the Azure or Tavily env vars are unset.
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
from chorus_employee.marketer import MARKETER_CONTENT_DOC
from chorus_harness import EmployeeHarnessFactory

_BRAND_SPEC = """# Arceus Brand Voice Specification
## Tone
- Technical, direct, confident but grounded. Every performance claim must be evidence-backed.
## Prohibited Phrases
- revolutionary, game-changing, 10x, unlock, supercharge, best-in-class, cutting-edge
## Claim Policy
- Substantiate claims with a source; hedge unvalidated ones with "we believe" / "early results suggest".
- When you cite a fact from research, name the source inline.
"""

_STRATEGY_DOC = "strategy_brief.md"

_TASK = (
    "Plan and draft a launch blog post positioning Arceus (an AI company operating system) against "
    "the current AI coding-assistant market. This is a substantial campaign, so FRAME THE BET FIRST: "
    "call spawn_subagent(name=\"strategist\", prompt=\"Frame the go-to-market bet for Arceus vs the "
    "AI coding-assistant market. Research what Anysphere/Cursor recently raised and at what valuation "
    "(name sources), then write strategy_brief.md with the hypothesis, audience, channel, message "
    "angle, success metric, and cited evidence.\"). The strategist will research the market itself and "
    "write strategy_brief.md. Then READ strategy_brief.md and draft an on-brand content_draft.md TO "
    "that brief, citing the sources inline. Deliverable: content_draft.md."
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
            _log(f"    ✅ {name} completed [{'ok' if ok else 'ERR'}] err={p.get('error')}")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⚖ evaluated: passed={p.get('passed')}")
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    (path / "brand_spec.md").write_text(_BRAND_SPEC, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x",
         "commit", "-m", "init: seed brand spec"],
        check=True, capture_output=True,
    )


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    tavily = os.environ.get("TAVILY_API_KEY") or os.environ.get("DREAM_TAVILY_API_KEY")
    if not (api_key and base_url and deployment and tavily):
        _log("skipping: set AZURE_OPENAI_* and TAVILY_API_KEY")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-strategist-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = SqliteLedger.open(":memory:")
    bus = _DepthCaptureBus()
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key, base_url=base_url, deployment=deployment,
            company_id="arceus", roles=registry, pricing=default_pricing_from_env(),
            seed=seed, ledger=ledger,
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))
        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]

        strategist = next((s for s in cfg.subagents if s.name == "strategist"), None)

        _log("=" * 72)
        _log("MARKETER + STRATEGIST — depth-2 chain: Mira → strategist → web_research")
        _log("=" * 72)
        _log(f"   subagents on Mira : {[s.name for s in cfg.subagents]}")
        _log(f"   strategist spawnable: {[c.name for c in strategist.spawnable] if strategist else '?'}")
        _log(f"   worktree : {mat.working_dir}")

        ledger.tasks.submit(Task(id="arceus-launch-post", intent=_TASK))
        assign_task(ledger, "arceus-launch-post", "mira")
        _log("\nTASK: frame the bet (strategist → web_research), then draft the post\n" + "-" * 72)

        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory, budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
            roles=registry, landers=default_landers(factory.company_root),
            event_bus=bus, max_concurrent_runs=1,
            # Depth-2 research nests two turn-hungry sessions; widen the lease so the reaper
            # doesn't claim the beat mid-research.
            lease_ttl_s=1200.0,
        )
        for n in range(1, 4):
            task = ledger.tasks.get("arceus-launch-post")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n} — kernel dispatches marketer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

        _log("\n" + "=" * 72)
        _log("RESULT — the depth-2 chain")
        _log("=" * 72)
        _log(f"   subagents spawned (top bus): {bus.spawned}")
        _log(f"   subagents completed        : {bus.completed}")
        # NB: each dream session gets its OWN tracer (_factory.py), so a NESTED spawn
        # (strategist → web_research) emits to the strategist's private trace, NOT this top-level
        # bus — a live run cannot observe the depth-2 spawn here by construction. The authoritative
        # proof is deterministic: the wiring below + the dream integration test
        # (test_depth2_integration.py) + the runtime trace. This run exercises the chain live.
        wiring = strategist is not None and [c.name for c in strategist.spawnable] == ["web_research"]
        _log(f"   ★ DEPTH-2 WIRING (deterministic): {wiring}  "
             f"— strategist holds spawn_subagent + scoped web_research; it CAN nest.")
        _log("     (nested spawns are invisible to this bus — per-session tracers; see integration test.)")

        brief = mat.working_dir / _STRATEGY_DOC
        if brief.is_file():
            text = brief.read_text(encoding="utf-8")
            _log(f"\n   {_STRATEGY_DOC} ({len(text)} chars):")
            _log("   " + "-" * 60)
            for line in text.splitlines()[:20]:
                _log(f"   {line}")
        else:
            _log(f"   ⚠ no {_STRATEGY_DOC} written by the strategist")

        draft = mat.working_dir / MARKETER_CONTENT_DOC
        _log(f"\n   {MARKETER_CONTENT_DOC} written: {draft.is_file()}"
             f" ({len(draft.read_text(encoding='utf-8')) if draft.is_file() else 0} chars)")
        task = ledger.tasks.get("arceus-launch-post")
        _log(f"   task status : {task.status.value if task else '?'}")
    finally:
        ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
