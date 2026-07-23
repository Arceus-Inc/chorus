"""Marketer + web_search — Mira researches a live topic, then writes an on-brand post (§06/§07).

She uses dream's Tavily-backed ``web_search`` (an allowlisted-egress read at the REPO_WRITE_NET tier)
to gather current information on **AI tech startups**, then drafts a post to ``content_draft.md`` and
self-reviews it with the Brand-Critic. Proves the read-research half of her loop end to end.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... \
    TAVILY_API_KEY=... uv run python examples/marketer_web_search_run.py

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
    "Write a ~500-word blog post for a technical audience about the current state of AI tech "
    "startups. FIRST research it: call the web_search tool for recent, real information — notable "
    "startups, funding, and trends from the last year — running a few focused queries. THEN write an "
    "on-brand post to content_draft.md grounded in what you found, citing sources inline for any "
    "specific claim. Finally, spawn the brand_critic to check it against brand_spec.md; apply its "
    "fixes. Deliverable: the finished content_draft.md."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class LoggingBus(EventBus):
    """Print the beat's events, highlighting web_search calls + their results."""

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self._buf = ""

    def _flush(self) -> None:
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
        self._flush()
        if event.kind is EventKind.RUN_TOOL_USE:
            tool = p.get("tool", "?")
            if tool == "web_search":
                _log(f"    🔎 web_search  {str(p.get('input', ''))[:200]}")
            elif tool == "spawn_subagent":
                _log(f"    🔀 spawn_subagent  {str(p.get('input', ''))[:140]}")
            else:
                _log(f"    → {tool}  {str(p.get('input', ''))[:120]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tool = p.get("tool", "?")
            tag = "ERR" if p.get("is_error") else "ok"
            if tool == "web_search":
                _log(f"    🔎 results [{tag}]: {str(p.get('content', ''))[:260]}")
            elif tool == "spawn_subagent":
                _log(f"    🔀 critic [{tag}]: {str(p.get('content', ''))[:180]}")
            else:
                _log(f"    ← {tool} [{tag}]")
        elif event.kind is EventKind.SUBAGENT_COMPLETED:
            _log(f"    ✅ {p.get('subagent_name', '?')}: {str(p.get('content', ''))[:160]}")
        elif event.kind is EventKind.RUN_STARTED:
            _log("    ▸ beat started")
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

    base = Path(tempfile.mkdtemp(prefix="chorus-websearch-"))
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
            ledger=ledger,
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))
        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]

        _log("=" * 72)
        _log("MARKETER + WEB SEARCH — research a live topic, then write on-brand")
        _log("=" * 72)
        _log("   employee : mira (marketer)")
        _log(f"   web_search present: {'web_search' in cfg.tools}   sandbox: {cfg.sandbox}")
        _log(f"   worktree : {mat.working_dir}")

        ledger.tasks.submit(Task(id="ai-startups-post", intent=_TASK))
        assign_task(ledger, "ai-startups-post", "mira")
        _log("\nTASK: research AI tech startups on the web, then write a post\n" + "-" * 72)

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
            task = ledger.tasks.get("ai-startups-post")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n} — kernel dispatches marketer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

        _log("\n" + "=" * 72)
        _log("RESULT")
        _log("=" * 72)
        task = ledger.tasks.get("ai-startups-post")
        _log(f"   task status : {task.status.value if task else '?'}")
        doc = mat.working_dir / MARKETER_CONTENT_DOC
        if doc.is_file():
            text = doc.read_text(encoding="utf-8")
            _log(f"   content_draft.md ({len(text)} chars):")
            _log("   " + "-" * 60)
            for line in text.splitlines()[:30]:
                _log(f"   {line}")
        else:
            _log("   ⚠ no content_draft.md written")
    finally:
        ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
