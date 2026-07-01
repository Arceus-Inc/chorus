"""Marketer go-live gate — Mira stages an irreversible publish; a human authorises it (§07/§11).

The marketer's crux is *draft-and-stage, gate-out*. Here the draft is already final and brand-approved
(seeded into her worktree), so the beat exercises the NEW surface: Mira calls the ``stage_go_live``
tool to publish it — which does NOT publish. It opens a human approval gate and parks the task
BLOCKED. A person then approves (or denies), and only then does the go-live proceed.

Two modes, one persistent ledger:

    # 1) run the beat — Mira stages the publish; leaves the gate pending
    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... \
    GOLIVE_DEMO_DIR=/tmp/golive uv run python examples/marketer_go_live_run.py

    # 2) resolve it as the human approver (no model, no keys)
    GOLIVE_DEMO_DIR=/tmp/golive uv run python examples/marketer_go_live_run.py resolve approve
    GOLIVE_DEMO_DIR=/tmp/golive uv run python examples/marketer_go_live_run.py resolve deny

Skips cleanly (exit 0) when the Azure env vars are unset (stage mode only).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.governance import ApprovalDecision, GovernanceResolver
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
- Hedge unvalidated benefits with "we believe" / "early results suggest".
"""

# A final, brand-approved draft — this run is about GOING LIVE, not drafting (that's the prior slice).
_FINAL_DRAFT = """# Why technical founders should look at Arceus

If you have shipped software for any length of time, you know the tax is coordination: turning an
idea into a scoped sprint, lining up checks, and keeping quality from slipping as scope grows.

Arceus (arceus.sh) coordinates a team of LLM agents to plan sprints, draft changes, run QA, and
prepare releases for your approval. You act as the board of directors: you set direction and gate
what ships. We believe this shifts your time from coordination toward the decisions only you can make.

Early results suggest teams spend less time on status pings and ticket grooming. Nothing ships
without your sign-off, and every agent's work is inspectable: what it changed, why, and what it
verified. If you are small and moving fast, that is the point — momentum without losing the plot.
"""

_TASK = (
    "The file content_draft.md in your worktree is FINAL and brand-approved. Your only job is to take "
    "it live: publish it to the company blog. Do this by calling the stage_go_live tool exactly once "
    "with action='publish', target='company blog', content_ref='content_draft.md'. Do not edit the "
    "draft or write any other file. After staging, you are done."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class LoggingBus(EventBus):
    """Print the beat's events, highlighting the go-live tool call + its gated result."""

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
            if tool == "stage_go_live":
                _log(f"    🚀 CALL stage_go_live  {str(p.get('input', ''))[:200]}")
            else:
                _log(f"    → {tool}  {str(p.get('input', ''))[:120]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tool = p.get("tool", "?")
            if tool == "stage_go_live":
                for line in str(p.get("content", "")).splitlines():
                    _log(f"    🔒 {line}")
            else:
                tag = "ERR" if p.get("is_error") else "ok"
                _log(f"    ← {tool} [{tag}]")
        elif event.kind is EventKind.RUN_STARTED:
            _log("    ▸ beat started")
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    (path / "brand_spec.md").write_text(_BRAND_SPEC, encoding="utf-8")
    (path / MARKETER_CONTENT_DOC).write_text(_FINAL_DRAFT, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x",
         "commit", "-m", "init: seed brand spec + final draft"],
        check=True, capture_output=True,
    )


def _base() -> Path:
    env = os.environ.get("GOLIVE_DEMO_DIR")
    base = Path(env) if env else Path(tempfile.mkdtemp(prefix="chorus-golive-"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _stage(base: Path) -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping stage: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    seed = base / "source"
    _seed_repo(seed)
    ledger = SqliteLedger.open(str(base / "ledger.db"))  # persistent — the resolve step reopens it
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key, base_url=base_url, deployment=deployment,
            company_id="arceus", roles=registry, pricing=default_pricing_from_env(),
            seed=seed, ledger=ledger,  # ledger= binds the stage_go_live capability tool
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))
        cfg = role_beat_config(registry.get("marketer").manifest)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]

        _log("=" * 72)
        _log("MARKETER GO-LIVE GATE — stage a publish, gate on human approval")
        _log("=" * 72)
        _log("   employee : mira (marketer)")
        _log(f"   go-live tool present: {'stage_go_live' in cfg.tools}")
        _log(f"   worktree : {mat.working_dir}")
        _log(f"   content_draft.md seeded final: {(mat.working_dir / MARKETER_CONTENT_DOC).exists()}")

        ledger.tasks.submit(Task(id="arceus-golive", intent=_TASK))
        assign_task(ledger, "arceus-golive", "mira")
        _log("\nTASK: take the final draft live (publish) — must stage for approval\n" + "-" * 72)

        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory, budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
            roles=registry, landers=default_landers(factory.company_root),
            event_bus=LoggingBus(), max_concurrent_runs=1,
        )
        for n in range(1, 4):
            task = ledger.tasks.get("arceus-golive")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n} — kernel dispatches marketer beat")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())

        _log("\n" + "=" * 72)
        _log("RESULT — staged, awaiting a human")
        _log("=" * 72)
        task = ledger.tasks.get("arceus-golive")
        _log(f"   task status : {task.status.value if task else '?'}")
        pending = ledger.approvals.pending()
        if pending:
            gate = pending[0]
            _log(f"   ★ GATE OPEN : {gate.id}")
            _log(f"     reason    : {gate.reason}")
            _log(f"     gate_kind : {gate.gate_kind.value if gate.gate_kind else '?'}  (approve → task proceeds)")
            _log("   nothing published — reach is fail-closed behind this gate.")
        else:
            _log("   ⚠ no gate opened — Mira did not call stage_go_live")
        _log(f"\n   ledger    : {base / 'ledger.db'}")
        _log(f"   resolve   : GOLIVE_DEMO_DIR={base} uv run python examples/marketer_go_live_run.py resolve <approve|deny>")
    finally:
        ledger.close()
    return 0


def _resolve(base: Path, decision: str) -> int:
    ledger = SqliteLedger.open(str(base / "ledger.db"))
    try:
        pending = ledger.approvals.pending()
        if not pending:
            _log("no pending gate to resolve (run the stage step first)")
            return 1
        gate = pending[0]
        verdict = ApprovalDecision.APPROVE if decision == "approve" else ApprovalDecision.DENY
        _log("=" * 72)
        _log(f"HUMAN DECISION: {verdict.value.upper()} — gate {gate.id}")
        _log("=" * 72)
        _log(f"   {gate.reason}")
        GovernanceResolver(ledger).resolve(
            gate.id, decision=verdict, decided_by_user_id="board", now=datetime.now(UTC)
        )
        task = ledger.tasks.get(gate.subject_id)
        _log(f"\n   gate status : {ledger.approvals.get(gate.id).status.value}")  # type: ignore[union-attr]
        _log(f"   task status : {task.status.value if task else '?'}")
        if verdict is ApprovalDecision.APPROVE:
            _log("   → authorised: the go-live may now proceed (the real publish is a later slice).")
        else:
            _log("   → denied: nothing goes live; the draft stays staged.")
    finally:
        ledger.close()
    return 0


def main(argv: list[str]) -> int:
    base = _base()
    if len(argv) >= 2 and argv[0] == "resolve":
        return _resolve(base, argv[1])
    return _stage(base)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
