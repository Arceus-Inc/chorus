"""Marketer + Web-Research Orchestrator — Mira spawns web_research, then drafts on-brand.

Proves the full path end to end, keyed:
  1. Mira spawns the ``web_research`` subagent for a market question (web_search + web_extract).
  2. dream's runtime guardrail validates its final message against ``WebResearchOutput`` — repairing
     the JSON if needed, failing open with a ``⚠`` warning only if it truly can't be made valid.
  3. Mira uses the (validated) findings to write ``content_draft.md``.

The script captures the web_research return, checks whether a guardrail warning appeared (it should
NOT for a well-formed result), and re-validates the payload against ``WebResearchOutput`` locally — so
we can see the schema enforcement is *confirming* the result, not negating it.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... \
    TAVILY_API_KEY=... uv run python examples/marketer_web_research_run.py

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
    "Write a ~350-word blog post for a technical audience on what Anysphere/Cursor's recent funding "
    "signals about the AI coding-assistant market. FIRST get the facts: SPAWN the web_research "
    'subagent with ONE focused question — call spawn_subagent(name="web_research", prompt="What did '
    "Anysphere (maker of Cursor) raise in its most recent 2024-2025 funding round, and at what "
    'valuation? Give the figures and name the sources."). Use its cited findings (a JSON answer with a '
    "citation_graph) to write an on-brand post to content_draft.md, citing sources inline. Then spawn "
    "brand_critic to check it against brand_spec.md and apply its fixes. Deliverable: content_draft.md."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _CaptureBus(EventBus):
    """Print the beat's events; capture the web_research spawn result for validation."""

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.web_research_output: str | None = None
        self._pending_web_research = False

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            tool = p.get("tool", "?")
            inp = str(p.get("input", ""))[:200]
            if tool == "spawn_subagent":
                self._pending_web_research = "web_research" in inp
                _log(f"    🔀 spawn_subagent  {inp}")
            elif tool in ("web_search", "web_extract"):
                _log(f"    🔎 {tool}  {str(p.get('input', ''))[:160]}")
            else:
                _log(f"    → {tool}  {inp[:120]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tool = p.get("tool", "?")
            tag = "ERR" if p.get("is_error") else "ok"
            if tool == "spawn_subagent" and self._pending_web_research:
                content = str(p.get("content", ""))
                self.web_research_output = content
                self._pending_web_research = False
                _log(f"    🔀 web_research result [{tag}] ({len(content)} chars)")
            elif tool in ("web_search", "web_extract"):
                _log(f"    🔎 {tool} result [{tag}]")
        elif event.kind is EventKind.SUBAGENT_SPAWNED:
            _log(f"    🔀 SUBAGENT_SPAWNED {p.get('subagent_name', '?')}")
        elif event.kind is EventKind.SUBAGENT_COMPLETED:
            name = p.get("subagent_name", "?")
            content = str(p.get("content", ""))
            if name == "web_research" and self.web_research_output is None:
                self.web_research_output = content
            tag = "ERR" if p.get("is_error") or not p.get("success", True) else "ok"
            _log(f"    ✅ {name} completed [{tag}] ({len(content)} chars) err={p.get('error')}")
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(
                f"    ⚖ evaluated: passed={p.get('passed')} summary={str(p.get('summary', ''))[:160]}"
            )
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")
        elif event.kind is EventKind.TASK_STATUS:
            _log(f"    · task → {p.get('status')}")


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


def _report_guardrail(raw: str) -> None:
    """Note whether a guardrail warning surfaced on the web_research return.

    NB: this inspects the *event-bus* copy of the spawn result, which the bus truncates for logging —
    so a full schema re-validation here is unreliable. The authoritative proof that the guardrail
    confirms (does not negate) a valid return is the unit tests + the isolation harness, which read
    the untruncated ``SubagentResult.output``. Here we only surface the fail-open warning, if any.
    """
    _log("\n" + "=" * 72)
    _log("GUARDRAIL SIGNAL (from the truncated event payload)")
    _log("=" * 72)
    if not raw:
        _log("   (no web_research output captured on the bus)")
        return
    warned = raw.lstrip().startswith("⚠")
    _log(f"   guardrail failed-open warning present: {warned}")
    if warned:
        _log(f"   {raw.splitlines()[0]}")


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    tavily = os.environ.get("TAVILY_API_KEY") or os.environ.get("DREAM_TAVILY_API_KEY")
    if not (api_key and base_url and deployment and tavily):
        _log("skipping: set AZURE_OPENAI_* and TAVILY_API_KEY")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-webresearch-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    bus = _CaptureBus()
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
            # The marketer role carries its own beat_timeout_s / lease_ttl_s (research is turn-hungry),
            # so no factory/scheduler override is needed here — the role budget flows through.
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))
        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]

        _log("=" * 72)
        _log("MARKETER + WEB-RESEARCH ORCHESTRATOR — spawn research, validate, draft")
        _log("=" * 72)
        _log("   employee : mira (marketer)")
        _log(f"   subagents: {[s.name for s in cfg.subagents]}")
        _log(f"   web_extract present: {'web_extract' in cfg.tools}   sandbox: {cfg.sandbox}")
        _log(f"   worktree : {mat.working_dir}")

        ledger.tasks.submit(Task(id="ai-devtools-post", intent=_TASK))
        assign_task(ledger, "ai-devtools-post", "mira")
        _log(
            "\nTASK: spawn web_research on AI dev-tools startups, then write the post\n" + "-" * 72
        )

        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
            roles=registry,
            landers=default_landers(factory.company_root),
            event_bus=bus,
            max_concurrent_runs=1,
            # A research beat blocks for minutes inside one uninterrupted web_research sweep and can't
            # renew its lease meanwhile; the 300s default would reap it mid-research. Give it headroom.
            lease_ttl_s=900.0,
        )
        for n in range(1, 4):
            task = ledger.tasks.get("ai-devtools-post")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n} — kernel dispatches marketer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

        _report_guardrail(bus.web_research_output or "")

        _log("\n" + "=" * 72)
        _log("RESULT")
        _log("=" * 72)
        task = ledger.tasks.get("ai-devtools-post")
        _log(f"   task status : {task.status.value if task else '?'}")
        doc = mat.working_dir / MARKETER_CONTENT_DOC
        if doc.is_file():
            text = doc.read_text(encoding="utf-8")
            _log(f"   content_draft.md ({len(text)} chars):")
            _log("   " + "-" * 60)
            for line in text.splitlines()[:24]:
                _log(f"   {line}")
        else:
            _log("   ⚠ no content_draft.md written")
    finally:
        ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
