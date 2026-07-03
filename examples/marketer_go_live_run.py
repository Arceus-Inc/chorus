"""Marketer go-live — the full §05 dark node: stage → gate → human approves → EXECUTE → live.

Beat 1: Mira stages the final draft into the CMS (``cms_draft`` → an UNPUBLISHED Strapi draft,
invisible on the public blog) and opens the go-live gate (``stage_go_live``). Nothing ships.
A human then approves. Beat 2: Mira wakes and calls ``execute_go_live`` — fail-closed against the
ledger — which flips the Strapi draft to PUBLISHED: the post appears on http://localhost:1337/blog/.

Three modes, one persistent ledger + worktree:

    # 1) stage — Mira drafts into the CMS + opens the gate (needs Azure keys)
    GOLIVE_DEMO_DIR=/tmp/golive uv run python examples/marketer_go_live_run.py

    # 2) the human decision (no model, no keys)
    GOLIVE_DEMO_DIR=/tmp/golive uv run python examples/marketer_go_live_run.py resolve approve

    # 3) execute — Mira wakes and publishes the approved reach (needs Azure keys)
    GOLIVE_DEMO_DIR=/tmp/golive uv run python examples/marketer_go_live_run.py publish

Skips cleanly (exit 0) when the Azure env vars are unset (model modes only).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
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

# A final, brand-approved draft — this run is about GOING LIVE, not drafting (that's a prior slice).
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
    "The file content_draft.md in your worktree is FINAL and brand-approved. Your job is to take it "
    "live on the company blog, through the gate. PROBE FIRST, every beat:\n"
    "1. Your FIRST tool call is execute_go_live(content_type='blog') — fail-closed and safe to call "
    "blind; its answer tells you the true state. If it publishes: report the live URL and finish. "
    "If it says the gate is PENDING: stop and wait for the human. If DENIED: note that and finish.\n"
    "2. ONLY if it says no gate exists / nothing staged: call cms_draft(content_type='blog', "
    "title=<the H1 of the draft>, body=<the full draft text>), then stage_go_live(action='publish', "
    "target='company blog', content_ref='content_draft.md') exactly once, and STOP — a human must "
    "approve before anything goes live.\n"
    "Never edit the draft; never publish without the gate; never re-stage when a gate already exists."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class LoggingBus(EventBus):
    """Print the beat's events, highlighting the gate + executor calls."""

    _SPOTLIGHT: ClassVar[dict[str, str]] = {
        "stage_go_live": "🚀", "cms_draft": "📄", "execute_go_live": "🟢",
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
        return  # already seeded (publish mode reuses the stage worktree)
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


def _public_post_status(document_id: str) -> str:
    """What the PUBLIC blog API says about a post: 'published' | 'invisible' | 'unreachable'."""
    url = os.environ.get("STRAPI_URL", "http://localhost:1337")
    try:
        with urllib.request.urlopen(f"{url}/api/blog-posts/{document_id}", timeout=10) as resp:
            data = json.loads(resp.read()).get("data") or {}
            return "published" if data.get("publishedAt") else "invisible"
    except urllib.error.HTTPError as err:
        return "invisible" if err.code == 404 else "unreachable"
    except OSError:
        return "unreachable"


def _staged_document_id(working_dir: Path, task_id: str) -> str | None:
    """The Strapi documentId Mira staged, from the worktree's standing-draft index."""
    index = working_dir / ".harness" / "cms-drafts.json"
    if not index.exists():
        return None
    entry = json.loads(index.read_text(encoding="utf-8")).get(f"blog:{task_id}")
    return entry.get("ref_id") if isinstance(entry, dict) else None


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
        _log("STEP 1/3 — STAGE: draft into the CMS + open the go-live gate")
        _log("=" * 72)
        _log(f"   worktree : {mat.working_dir}")

        ledger.tasks.submit(Task(id="arceus-golive", intent=_TASK))
        assign_task(ledger, "arceus-golive", "mira")

        scheduler = _scheduler(ledger, factory, registry)
        for n in range(1, 4):
            task = ledger.tasks.get("arceus-golive")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n}")
            _tick(scheduler)

        _log("\n" + "=" * 72)
        _log("STAGED — awaiting the human")
        _log("=" * 72)
        task = ledger.tasks.get("arceus-golive")
        _log(f"   task status : {task.status.value if task else '?'}")
        doc = _staged_document_id(mat.working_dir, "arceus-golive")
        if doc:
            _log(f"   CMS draft   : {doc} — public blog says: {_public_post_status(doc)}")
        pending = ledger.approvals.pending()
        if pending:
            _log(f"   ★ GATE OPEN : {pending[0].id} — {pending[0].reason}")
            _log("   nothing published — reach is fail-closed behind this gate.")
        else:
            _log("   ⚠ no gate opened — Mira did not call stage_go_live")
        _log(f"\n   next: GOLIVE_DEMO_DIR={base} uv run python examples/marketer_go_live_run.py resolve approve")
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
            _log(f"\n   next: GOLIVE_DEMO_DIR={base} uv run python examples/marketer_go_live_run.py publish")
        else:
            _log("   → denied: nothing goes live; execute_go_live will refuse.")
    finally:
        ledger.close()
    return 0


def _publish(base: Path) -> int:
    creds = _azure()
    if creds is None:
        _log("skipping publish: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    ledger = SqliteLedger.open(str(base / "ledger.db"))
    try:
        factory, registry = _factory(base, ledger, creds)
        mat = factory.materialize(ledger.employees.get("mira"))  # type: ignore[arg-type]
        doc = _staged_document_id(mat.working_dir, "arceus-golive")

        _log("=" * 72)
        _log("STEP 3/3 — EXECUTE: Mira publishes the approved reach")
        _log("=" * 72)
        if doc:
            _log(f"   before: public blog says {doc} is {_public_post_status(doc)}")

        scheduler = _scheduler(ledger, factory, registry)
        for n in range(1, 4):
            task = ledger.tasks.get("arceus-golive")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\nTICK {n}")
            _tick(scheduler)

        _log("\n" + "=" * 72)
        _log("RESULT — the dark node, closed")
        _log("=" * 72)
        task = ledger.tasks.get("arceus-golive")
        _log(f"   task status : {task.status.value if task else '?'}")
        deliveries = mat.working_dir / ".harness" / "deliveries.json"
        if deliveries.exists():
            for approval_id, record in json.loads(deliveries.read_text(encoding="utf-8")).items():
                _log(f"   ★ DELIVERED : gate {approval_id} → {record.get('url')}")
        if doc:
            status = _public_post_status(doc)
            marker = "★ LIVE ON THE BLOG" if status == "published" else f"⚠ {status}"
            _log(f"   {marker}: {os.environ.get('STRAPI_URL', 'http://localhost:1337')}/blog/#/post/{doc}")
    finally:
        ledger.close()
    return 0


def main(argv: list[str]) -> int:
    base = _base()
    if len(argv) >= 2 and argv[0] == "resolve":
        return _resolve(base, argv[1])
    if len(argv) >= 1 and argv[0] == "publish":
        return _publish(base)
    return _stage(base)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
