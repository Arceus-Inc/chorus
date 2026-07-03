"""Marketer + Creative/Copywriter subagent — the §10 variety path.

Mira writes a research-grounded seed post (``content_seed.md``), spawns the Creative subagent to
draft a handful of on-brand VARIANTS of it under ``candidates/`` (each self-linted via ``brand_lint``),
then prunes among {seed + variants} and promotes the strongest into ``content_draft.md`` — after which
the Brand-Critic reviews as usual. Selection stays with Mira; Creative only produces variety.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/marketer_creative_run.py

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
from chorus_employee.marketer import MARKETER_CONTENT_DOC
from chorus_harness import EmployeeHarnessFactory

# --- Arceus brand spec (seeded into the worktree so Creative + brand_lint can read it) ---
_BRAND_SPEC = """\
# Arceus Brand Voice Specification

## Tone
- Technical: Write for engineers and technical founders.
- Direct: Say what you mean in the fewest words. No filler, no hedging without cause.
- Confident but grounded: State capabilities clearly without inflating them.

## Anti-Personas (never sound like these)
- Hype marketer: "Revolutionary!", "Game-changing!", "10x your productivity!"
- Vague visionary: "Reimagine the future of work"
- Buzzword stacker: "AI-powered synergistic next-gen platform"

## Prohibited Phrases
- revolutionary, game-changing, groundbreaking, disruptive
- 10x, 100x (unless citing a measured benchmark)
- magic, magical, automagically
- unlock, unleash, supercharge
- best-in-class, world-class, cutting-edge, bleeding-edge

## Claim Policy
- Every performance claim MUST be substantiated with a specific metric or citation.
- Use "we believe" or "early results suggest" for unvalidated hypotheses.
- Never promise outcomes the product cannot guarantee today.
"""

_ARCEUS_CONTEXT = """\
Company: Arceus (arceus.sh)
Tagline: Your AI company, running autonomously.
What it is: An AI company operating system. Arceus boots a team of LLM agents that plan \
sprints, write code, run QA, and ship — while you act as the board of directors.
Target audience: Technical founders who move fast and want to ship without managing a team.
"""

_TASK = (
    "You are writing content for Arceus (arceus.sh). Here is the company context:\n\n"
    + _ARCEUS_CONTEXT
    + "\nWe want OPTIONS to choose from, so use the variety path:\n"
    "1. Write your grounded reference draft (400-600 words) to `content_seed.md` — on-brand, every "
    "claim hedged or substantiated per brand_spec.md.\n"
    "2. Spawn the `creative` subagent, handing it the seed, to draft 3 on-brand VARIANTS under "
    "`candidates/` (varying angle and hook, preserving every claim). It self-lints each and returns a "
    "manifest.\n"
    "3. Read the variants, pick or MERGE the strongest, and write THAT into `content_draft.md`.\n"
    "4. Spawn the `brand_critic` on content_draft.md and apply every fix it names.\n\n"
    "The DELIVERABLE is the finished `content_draft.md`. Done means it is on-voice per brand_spec.md, "
    "substantiates or hedges every claim, and is structured for the channel."
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
            tool_name = p.get("tool", "?")
            if tool_name == "spawn_subagent":
                _log(f"    🔀 SPAWN SUBAGENT: {str(p.get('input', ''))[:180]}")
            else:
                _log(f"    → TOOL {tool_name}  {str(p.get('input', ''))[:160]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tag = "ERR" if p.get("is_error") else "ok"
            tool_name = p.get("tool", "?")
            if tool_name == "spawn_subagent":
                _log(f"    🔀 SUBAGENT RESULT: {str(p.get('content', ''))[:300]}")
            else:
                note = f"  {str(p.get('content', ''))[:160]}" if p.get("is_error") else ""
                _log(f"    ← {tool_name} [{tag}]{note}")
        elif event.kind is EventKind.SUBAGENT_SPAWNED:
            _log(f"    🔀 SUBAGENT_SPAWNED: {p.get('subagent_name', '?')}")
        elif event.kind is EventKind.SUBAGENT_COMPLETED:
            tag = "ERR" if p.get("is_error") else "ok"
            _log(
                f"    ✅ SUBAGENT_COMPLETED: {p.get('subagent_name', '?')} [{tag}]"
                f"  {str(p.get('content', ''))[:280]}"
            )
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    ⊢ evaluated: {p.get('outcome', p)}")
        elif event.kind is EventKind.RUN_STARTED:
            _log("    ▸ beat started")
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")


def _seed_repo(path: Path) -> None:
    """Seed a repo with brand_spec.md — Creative + brand_lint need it."""
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# Arceus content workspace\n", encoding="utf-8")
    (path / "brand_spec.md").write_text(_BRAND_SPEC, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git", "-C", str(path),
            "-c", "user.name=s", "-c", "user.email=s@x",
            "commit", "-m", "init: seed with brand spec",
        ],
        check=True, capture_output=True,
    )


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-creative-"))
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
            # Binds the role's ledger-backed capability tools (brand_lint) so Creative can self-lint.
            ledger=ledger,
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))

        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("Marketer + Creative/Copywriter Subagent (§10 variety)")
        _log("=" * 72)
        _log("   employee : mira (marketer)")
        _log(f"   tools    : {', '.join(cfg.tools)}")
        _log("   subagents: creative (write), brand_critic (read-only), web_research")
        _log(f"   worktree : {mat.working_dir}")

        ledger.tasks.submit(Task(id="arceus-blog", intent=_TASK))
        assign_task(ledger, "arceus-blog", "mira")
        _log("")
        _log("TASK: seed → creative variants → prune → content_draft.md → brand_critic")
        _log("-" * 72)

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

        for n in range(1, 6):
            task = ledger.tasks.get("arceus-blog")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log("")
            _log(f"TICK {n} — kernel dispatches marketer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

            run = ledger.runs.for_task("arceus-blog")[-1]
            _log(f"   run status: {run.status.value}")

        wt = mat.working_dir
        _log("")
        _log("=" * 72)
        _log("RESULT")
        _log(f"   task status : {ledger.tasks.get('arceus-blog').status.value}")  # type: ignore[union-attr]

        seed_file = wt / "content_seed.md"
        _log(f"   content_seed.md present: {seed_file.exists()}")

        candidates_dir = wt / "candidates"
        variants = sorted(candidates_dir.glob("*.md")) if candidates_dir.is_dir() else []
        _log(f"   candidates/ variants   : {len(variants)}")
        for v in variants:
            words = len(v.read_text(encoding="utf-8").split())
            _log(f"      - {v.name} ({words} words)")

        content_file = wt / MARKETER_CONTENT_DOC
        if content_file.exists():
            content = content_file.read_text(encoding="utf-8")
            _log(f"   content_draft.md ({len(content)} chars):")
            _log("   " + "-" * 60)
            for line in content.splitlines()[:20]:
                _log(f"   {line}")
            if len(content.splitlines()) > 20:
                _log(f"   ... ({len(content.splitlines()) - 20} more lines)")
            _log("   " + "-" * 60)
        else:
            _log("   ⚠ no content_draft.md in worktree")

        artifacts = ledger.artifacts.list_for_task("arceus-blog")
        if artifacts:
            a = artifacts[0]
            _log(f"   ★ CONTENT ARTIFACT LANDED: type={a.type.value} ref={a.resource_ref}")
        else:
            _log("   no artifact landed yet.")
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
