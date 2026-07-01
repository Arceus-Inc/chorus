"""Marketer + Brand-Critic subagent — Mira drafts, spawns the critic, iterates.

Seeds a worktree with ``brand_spec.md`` (Arceus voice rules), hires a marketer,
assigns a content task, and ticks the kernel — the marketer drafts content then
spawns the Brand-Critic subagent mid-beat to validate against the voice spec.

This is the Slice 1 e2e: brief + manifest + subagent → beat → critic verdict → content.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/marketer_brand_critic_run.py

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
from chorus_employee.marketer import MARKETER_CONTENT_DOC
from chorus_harness import EmployeeHarnessFactory

# --- Arceus brand spec (seeded into the worktree for the Brand-Critic to read) ---
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

# --- The Arceus company context ---
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
    + "\nWrite a short blog post (400-600 words) to content_draft.md explaining what Arceus "
    "does and why technical founders should care.\n\n"
    "Use the brand_critic subagent as your self-review: spawn it to check content_draft.md "
    "against brand_spec.md, and apply every fix it names. The DELIVERABLE is the finished "
    "content_draft.md itself — done means the draft is on-voice per brand_spec.md, substantiates "
    "or hedges every claim, and is structured for the channel. (The critic is how you get there; "
    "the draft is what's judged.)"
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
            # Highlight subagent spawning
            if tool_name == "spawn_subagent":
                _log(f"    🔀 SPAWN SUBAGENT: {str(p.get('input', ''))[:160]}")
            else:
                _log(f"    → TOOL {tool_name}  {str(p.get('input', ''))[:160]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tag = "ERR" if p.get("is_error") else "ok"
            tool_name = p.get("tool", "?")
            if tool_name == "spawn_subagent":
                result_text = str(p.get("content", ""))[:300]
                _log(f"    🔀 CRITIC VERDICT: {result_text}")
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
    """Seed a repo with brand_spec.md — the critic needs it."""
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

    base = Path(tempfile.mkdtemp(prefix="chorus-brand-critic-"))
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
            # REQUIRED: binds the role's ledger-backed capability tools. Without it the factory skips
            # _capability_tool registration entirely, so brand_lint / stage_go_live never reach the
            # harness and the Brand-Critic can't run brand_lint.
            ledger=ledger,
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))

        # Show materialized harness config
        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("SLICE 1: Marketer + Brand-Critic Subagent")
        _log("=" * 72)
        _log("   employee : mira (marketer)")
        _log(f"   tools    : {', '.join(cfg.tools)}")
        _log("   subagents: brand_critic (read-only, max_turns=4)")
        _log(f"   worktree : {mat.working_dir}")
        _log(f"   brand_spec.md seeded: {(mat.working_dir / 'brand_spec.md').exists()}")

        # Submit + assign the task
        ledger.tasks.submit(Task(id="arceus-blog", intent=_TASK))
        assign_task(ledger, "arceus-blog", "mira")
        _log("")
        _log("TASK: Write Arceus blog post + validate with Brand-Critic")
        _log("-" * 72)

        # Tick the kernel — dispatch the beat
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

        for n in range(1, 5):
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

        # Show result
        wt = mat.working_dir
        _log("")
        _log("=" * 72)
        _log("RESULT")
        _log(f"   task status : {ledger.tasks.get('arceus-blog').status.value}")  # type: ignore[union-attr]
        content_file = wt / MARKETER_CONTENT_DOC
        if content_file.exists():
            content = content_file.read_text(encoding="utf-8")
            _log(f"   content_draft.md ({len(content)} chars):")
            _log("   " + "-" * 60)
            for line in content.splitlines()[:25]:
                _log(f"   {line}")
            if len(content.splitlines()) > 25:
                _log(f"   ... ({len(content.splitlines()) - 25} more lines)")
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
