"""Marketer email send — the second reach through the §05 gate: stage → approve → SEND live.

Beat 1: Mira stages the final email copy into the CMS (``cms_draft(email)`` → an UNSENT
email-campaign draft) and opens the go-live gate (``stage_go_live(send)``). Nothing sends.
A human approves. Beat 2: Mira wakes, probes with ``execute_go_live(content_type='email')`` —
fail-closed — and the APPROVED draft is sent over the configured transport: Resend (live email
in a real inbox) when ``RESEND_API_KEY`` is set, else the worktree file outbox. Routing
(EMAIL_FROM / EMAIL_TO) is operator env — the model never chooses recipients.

Three modes, one persistent ledger + worktree:

    # 1) stage — Mira drafts into the CMS + opens the gate (needs Azure keys)
    EMAILSEND_DEMO_DIR=/tmp/emailsend uv run python examples/marketer_email_send_run.py

    # 2) the human decision (no model, no keys)
    EMAILSEND_DEMO_DIR=/tmp/emailsend uv run python examples/marketer_email_send_run.py resolve approve

    # 3) execute — Mira wakes and SENDS the approved campaign (needs Azure keys)
    EMAILSEND_DEMO_DIR=/tmp/emailsend uv run python examples/marketer_email_send_run.py send

Skips cleanly (exit 0) when the Azure env vars are unset (model modes only).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.governance import ApprovalDecision, GovernanceResolver
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.observability import EventBus
from chorus.roles import RoleRegistry, default_roles
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

# A final, brand-approved email — this run is about SENDING through the gate, not drafting.
_FINAL_EMAIL = """# Arceus early access is open

Hi there,

You asked us to tell you when Arceus was ready for real projects. Early access is open now.

Arceus (arceus.sh) coordinates a team of LLM agents that plan sprints, draft changes, run QA,
and prepare releases for your approval. You act as the board: you set direction and gate what
ships. We believe this shifts your time from coordination toward the decisions only you can make.

Early results suggest teams spend less time on status pings and ticket grooming. Nothing ships
without your sign-off, and every agent's work is inspectable — what it changed, why, and what it
verified.

What early access includes:
- A hosted workspace with the full agent team
- The governance console: approvals, budgets, audit trail
- Direct line to the founding team while we harden the edges

If you are small and moving fast, that is the point — momentum without losing the plot.

Reply to this email and we will set up your workspace within a day.

— The Arceus team
"""

_TASK = (
    "The file content_draft.md in your worktree is the FINAL, brand-approved copy of an early-access "
    "announcement email. Your job is to send it, through the gate. PROBE FIRST, every beat:\n"
    "1. Your FIRST tool call is execute_go_live(content_type='email') — fail-closed and safe to call "
    "blind; its answer tells you the true state. If it sends: report where the delivery landed and "
    "finish. If it says the gate is PENDING: stop and wait for the human. If DENIED: note that and "
    "finish.\n"
    "2. ONLY if it says no gate exists / nothing staged: call cms_draft(content_type='email', "
    "subject='Arceus early access is open', body=<the full draft text>, preheader='Early access is "
    "open — reply to claim your workspace'), then stage_go_live(action='send', target='early-access "
    "list', content_ref='content_draft.md') exactly once, and STOP — a human must approve before "
    "anything sends.\n"
    "You never choose recipients — the audience is operator config. Never edit the draft; never send "
    "without the gate; never re-stage when a gate already exists."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class LoggingBus(EventBus):
    """Print the beat's events, highlighting the gate + executor calls."""

    _SPOTLIGHT: ClassVar[dict[str, str]] = {
        "stage_go_live": "🚀", "cms_draft": "📄", "execute_go_live": "📬",
    }

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self._buf = ""

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TEXT:
            self._buf += str(p.get("text", ""))
            while "\n" in self._buf:
                head, self._buf = self._buf.split("\n", 1)
                if head.strip():
                    _log(f"    · {head.strip()[:200]}")
            return
        if event.kind is EventKind.RUN_TOOL_USE:
            tool = str(p.get("tool", "?"))
            mark = self._SPOTLIGHT.get(tool, "→")
            _log(f"    {mark} {tool}  {str(p.get('input', ''))[:160]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tool = str(p.get("tool", "?"))
            if tool in self._SPOTLIGHT:
                for line in str(p.get("content", "")).splitlines()[:4]:
                    _log(f"      {line[:180]}")
            elif p.get("is_error"):
                _log(f"    ← {tool} [ERR] {str(p.get('content', ''))[:120]}")
        elif event.kind is EventKind.RUN_STARTED:
            _log("    ▸ beat started")
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")


def _seed_repo(path: Path) -> None:
    if (path / ".git").exists():
        return  # already seeded (send mode reuses the stage worktree)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    (path / "brand_spec.md").write_text(_BRAND_SPEC, encoding="utf-8")
    (path / MARKETER_CONTENT_DOC).write_text(_FINAL_EMAIL, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x",
         "commit", "-m", "init: seed brand spec + final email"],
        check=True, capture_output=True,
    )


def _base() -> Path:
    env = os.environ.get("EMAILSEND_DEMO_DIR")
    base = Path(env) if env else Path(tempfile.mkdtemp(prefix="chorus-emailsend-"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _azure() -> tuple[str, str, str] | None:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        return None
    return api_key, base_url, deployment


def _factory(
    base: Path, ledger: SqliteLedger, creds: tuple[str, str, str]
) -> tuple[EmployeeHarnessFactory, RoleRegistry]:
    api_key, base_url, deployment = creds
    registry = RoleRegistry.from_plugins(default_roles())
    factory = EmployeeHarnessFactory(
        api_key=api_key, base_url=base_url, deployment=deployment,
        company_id="arceus", roles=registry,
        pricing=default_pricing_from_env(), seed=base / "source", ledger=ledger,
    )
    return factory, registry


def _tick(scheduler: Scheduler) -> None:
    async def _pulse() -> None:
        await scheduler.tick_once()
        await scheduler.drain()

    asyncio.run(_pulse())


def _scheduler(
    ledger: SqliteLedger, factory: EmployeeHarnessFactory, registry: RoleRegistry
) -> Scheduler:
    return Scheduler(
        ledger=ledger, workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=factory, budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
        roles=registry, landers=default_landers(factory.company_root),
        event_bus=LoggingBus(), max_concurrent_runs=1,
    )


def _transport_label() -> str:
    if os.environ.get("RESEND_API_KEY"):
        return f"resend (LIVE) → {os.environ.get('EMAIL_TO', '?')}"
    return "outbox (keyless file)"


def _deliveries(working_dir: Path) -> dict[str, dict[str, str]]:
    path = working_dir / ".harness" / "deliveries.json"
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _stage(base: Path) -> int:
    creds = _azure()
    if creds is None:
        _log("skipping stage: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    _seed_repo(base / "source")
    ledger = SqliteLedger.open(str(base / "ledger.db"))
    try:
        factory, registry = _factory(base, ledger, creds)
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]

        _log("=" * 72)
        _log("STEP 1/3 — STAGE: email into the CMS + open the go-live(send) gate")
        _log("=" * 72)
        _log(f"   worktree  : {mat.working_dir}")
        _log(f"   transport : {_transport_label()}")

        ledger.tasks.submit(Task(id="arceus-emailsend", intent=_TASK))
        assign_task(ledger, "arceus-emailsend", "mira")

        scheduler = _scheduler(ledger, factory, registry)
        for n in range(1, 4):
            task = ledger.tasks.get("arceus-emailsend")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n}")
            _tick(scheduler)

        _log("\n" + "=" * 72)
        _log("STAGED — awaiting the human; NOTHING has been sent")
        _log("=" * 72)
        task = ledger.tasks.get("arceus-emailsend")
        _log(f"   task status : {task.status.value if task else '?'}")
        pending = ledger.approvals.pending()
        if pending:
            _log(f"   ★ GATE OPEN : {pending[0].id} — {pending[0].reason}")
        else:
            _log("   ⚠ no gate opened — Mira did not call stage_go_live")
        _log(f"\n   next: EMAILSEND_DEMO_DIR={base} uv run python examples/marketer_email_send_run.py resolve approve")
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
        _log(f"STEP 2/3 — HUMAN DECISION: {verdict.value.upper()} — gate {gate.id}")
        _log("=" * 72)
        _log(f"   {gate.reason}")
        GovernanceResolver(ledger).resolve(
            gate.id, decision=verdict, decided_by_user_id="board", now=datetime.now(UTC)
        )
        task = ledger.tasks.get(gate.subject_id)
        _log(f"\n   gate status : {ledger.approvals.get(gate.id).status.value}")  # type: ignore[union-attr]
        _log(f"   task status : {task.status.value if task else '?'} (approve re-wakes Mira)")
        if verdict is ApprovalDecision.APPROVE:
            _log(f"\n   next: EMAILSEND_DEMO_DIR={base} uv run python examples/marketer_email_send_run.py send")
        else:
            _log("   → denied: nothing sends; execute_go_live will refuse.")
    finally:
        ledger.close()
    return 0


def _send(base: Path) -> int:
    creds = _azure()
    if creds is None:
        _log("skipping send: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    ledger = SqliteLedger.open(str(base / "ledger.db"))
    try:
        factory, registry = _factory(base, ledger, creds)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]

        _log("=" * 72)
        _log("STEP 3/3 — EXECUTE: Mira sends the approved campaign")
        _log("=" * 72)
        _log(f"   transport : {_transport_label()}")

        scheduler = _scheduler(ledger, factory, registry)
        for n in range(1, 4):
            task = ledger.tasks.get("arceus-emailsend")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n}")
            _tick(scheduler)

        _log("\n" + "=" * 72)
        _log("RESULT — the send edge, closed")
        _log("=" * 72)
        task = ledger.tasks.get("arceus-emailsend")
        _log(f"   task status : {task.status.value if task else '?'}")
        for approval_id, record in _deliveries(mat.working_dir).items():
            _log(f"   ★ DELIVERED : gate {approval_id} → action={record.get('action')} "
                 f"backend={record.get('backend')} ref={record.get('ref_id')}")
            _log(f"     {record.get('url')}")
        if not _deliveries(mat.working_dir):
            _log("   ⚠ no delivery recorded — the send did not execute")
    finally:
        ledger.close()
    return 0


def main(argv: list[str]) -> int:
    base = _base()
    if len(argv) >= 2 and argv[0] == "resolve":
        return _resolve(base, argv[1])
    if len(argv) >= 1 and argv[0] == "send":
        return _send(base)
    return _stage(base)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
