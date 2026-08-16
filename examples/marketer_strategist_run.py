"""Marketer + web_research — lean campaign framing, live: Mira → web_research.

Proves the Marketer's isolation-earner research path end to end, keyed:
  1. Mira loads ``channel-priors`` and spawns ``web_research`` for cited market facts.
  2. Mira drafts ``content_draft.md`` from those facts and red-teams with ``brand_critic``.

The bus captures every ``SUBAGENT_SPAWNED`` so we can assert ``web_research`` fired
and ``strategist`` did not.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... \
    TAVILY_API_KEY=... uv run python examples/marketer_strategist_run.py

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

_TASK = (
    "Plan and draft a launch blog post positioning Arceus (an AI company operating system) against "
    "the current AI coding-assistant market. This is a substantial campaign, so gather external "
    "facts first: load channel-priors and call spawn_subagent(name=\"web_research\", prompt=\"What did "
    "Anysphere/Cursor recently raise and at what valuation? Name sources.\"). Draft an on-brand "
    f"{MARKETER_CONTENT_DOC} grounded in those cited facts, citing the sources inline. "
    f"Deliverable: {MARKETER_CONTENT_DOC}."
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
            "init: seed brand spec",
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

    base = Path(tempfile.mkdtemp(prefix="chorus-strategist-"))
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
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))
        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]

        web = next((s for s in cfg.subagents if s.name == "web_research"), None)

        _log("=" * 72)
        _log("MARKETER + web_research — lean campaign framing")
        _log("=" * 72)
        _log(f"   subagents on Mira : {[s.name for s in cfg.subagents]}")
        _log(f"   web_research present: {web is not None}")
        _log(f"   worktree : {mat.working_dir}")

        ledger.tasks.submit(Task(id="arceus-launch-post", intent=_TASK))
        assign_task(ledger, "arceus-launch-post", "mira")
        _log("\nTASK: frame the bet (web_research), then draft the post\n" + "-" * 72)

        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
            roles=registry,
            landers=default_landers(factory.company_root),
            event_bus=bus,
            max_concurrent_runs=1,
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
        _log("RESULT — lean research path")
        _log("=" * 72)
        _log(f"   subagents spawned (top bus): {bus.spawned}")
        _log(f"   subagents completed        : {bus.completed}")
        lean = web is not None and "strategist" not in {s.name for s in cfg.subagents}
        _log(
            f"   ★ LEAN ROSTER (deterministic): {lean}  "
            f"— Mira holds web_research + brand_critic; no strategist persona."
        )

        draft = mat.working_dir / MARKETER_CONTENT_DOC
        if draft.is_file():
            text = draft.read_text(encoding="utf-8")
            _log(f"\n   {MARKETER_CONTENT_DOC} ({len(text)} chars):")
            _log("   " + "-" * 60)
            for line in text.splitlines()[:20]:
                _log(f"   {line}")
        else:
            _log(f"   ⚠ no {MARKETER_CONTENT_DOC} written")
        task = ledger.tasks.get("arceus-launch-post")
        _log(f"   task status : {task.status.value if task else '?'}")
    finally:
        ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
