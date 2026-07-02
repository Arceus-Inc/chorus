"""Marketer + cms_draft — Mira drafts content, then stages it into a real CMS as a draft.

Mira writes content_draft.md, self-reviews with the Brand-Critic, then calls ``cms_draft`` to stage
the finished post as an UNPUBLISHED draft. With STRAPI_URL + STRAPI_TOKEN set, the draft lands in the
live Strapi (verified here via a follow-up GET: it exists and ``publishedAt`` is null); without them,
the tool falls back to the keyless Markdown backend in the worktree.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=... \
    STRAPI_URL=http://localhost:1337 STRAPI_TOKEN=... STRAPI_COLLECTION=posts \
    uv run python examples/marketer_cms_draft_run.py

Skips cleanly (exit 0) when the Azure vars are unset.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

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
from chorus_harness import EmployeeHarnessFactory

_BRAND_SPEC = """\
# Arceus Brand Voice Specification

## Prohibited Phrases
- revolutionary, game-changing, groundbreaking, disruptive
- 10x, 100x (unless citing a measured benchmark)
- magic, magical, automagically
- unlock, unleash, supercharge

## Claim Policy
- Every performance claim MUST be substantiated with a specific metric or citation.
- Use "we believe" or "early results suggest" for unvalidated hypotheses.
"""

_TASK = (
    "You are writing content for Arceus (arceus.sh), an AI company operating system for technical "
    "founders.\n\n"
    "1. Write a short blog post (>= 300 words) to content_draft.md explaining what Arceus does and why "
    "technical founders should care. On-brand per brand_spec.md; hedge every performance claim.\n"
    "2. Self-review with the brand_critic subagent and apply its fixes until PASS.\n"
    "3. THEN stage the finished post into the CMS: call cms_draft(content_type=\"blog\", title=<a "
    "title>, body=<the full post>). This creates a reversible, unpublished draft — do NOT publish.\n\n"
    "The deliverable is content_draft.md, on-voice, plus a CMS draft staged via cms_draft."
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class LoggingBus(EventBus):
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
            tool = p.get("tool", "?")
            marker = "🎯 " if tool == "cms_draft" else "→ TOOL "
            _log(f"    {marker}{tool}  {str(p.get('input', ''))[:180]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tool = p.get("tool", "?")
            tag = "ERR" if p.get("is_error") else "ok"
            if tool == "cms_draft":
                _log(f"    🎯 cms_draft [{tag}]  {str(p.get('content', ''))[:280]}")
            elif tool == "spawn_subagent":
                _log(f"    🔀 critic: {str(p.get('content', ''))[:120]}")
            elif p.get("is_error"):
                _log(f"    ← {tool} [ERR]  {str(p.get('content', ''))[:140]}")
        elif event.kind is EventKind.RUN_DONE:
            _log("    ▪ beat done")


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# Arceus content workspace\n", encoding="utf-8")
    (path / "brand_spec.md").write_text(_BRAND_SPEC, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "init"],
        check=True, capture_output=True,
    )


def _verify_strapi(before_ids: set[str]) -> None:
    """Report the blog drafts Strapi holds now, flagging the one this run created (publishedAt null)."""
    base, token = os.environ.get("STRAPI_URL"), os.environ.get("STRAPI_TOKEN")
    if not (base and token):
        _log("   (Strapi env unset — cms_draft used the Markdown backend; check the worktree cms_drafts/)")
        return
    resp = httpx.get(
        f"{base.rstrip('/')}/api/blog-posts",
        params={"status": "draft"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20.0,
    )
    rows = resp.json().get("data", []) if resp.status_code == 200 else []
    fresh = [r for r in rows if r.get("documentId") not in before_ids]
    _log(f"   Strapi blog-posts drafts: {len(rows)} total, {len(fresh)} created by this run")
    for r in fresh:
        _log(f"     ★ documentId={r.get('documentId')} title={r.get('title')!r} publishedAt={r.get('publishedAt')}")


def _existing_draft_ids() -> set[str]:
    base, token = os.environ.get("STRAPI_URL"), os.environ.get("STRAPI_TOKEN")
    if not (base and token):
        return set()
    resp = httpx.get(
        f"{base.rstrip('/')}/api/blog-posts",
        params={"status": "draft"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20.0,
    )
    if resp.status_code != 200:
        return set()
    return {r.get("documentId") for r in resp.json().get("data", []) if r.get("documentId")}


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    before = _existing_draft_ids()
    base = Path(tempfile.mkdtemp(prefix="chorus-cms-draft-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = SqliteLedger.open(":memory:")
    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key, base_url=base_url, deployment=deployment, company_id="arceus",
            roles=registry, pricing=default_pricing_from_env(), seed=seed, ledger=ledger,
        )
        ledger.employees.create(Employee(id="mira", name="Mira", role="marketer"))
        cfg = role_beat_config(registry.get("marketer").manifest)
        _log("=" * 72)
        _log("Marketer + cms_draft (§08 CMS reversible write)")
        _log("=" * 72)
        _log(f"   cms_draft in tools: {'cms_draft' in cfg.tools}")
        backend = "strapi" if (os.environ.get("STRAPI_URL") and os.environ.get("STRAPI_TOKEN")) else "markdown"
        _log(f"   backend (by env)  : {backend}")

        ledger.tasks.submit(Task(id="arceus-blog", intent=_TASK))
        assign_task(ledger, "arceus-blog", "mira")
        _log("")
        _log("TASK: draft → brand_critic PASS → cms_draft into the CMS")
        _log("-" * 72)

        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"), roles=registry,
            landers=default_landers(factory.company_root), event_bus=LoggingBus(), max_concurrent_runs=1,
        )
        for n in range(1, 6):
            task = ledger.tasks.get("arceus-blog")
            if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log("")
            _log(f"TICK {n}")

            async def _pulse() -> None:
                await scheduler.tick_once()
                await scheduler.drain()

            asyncio.run(_pulse())
            _log(f"   run status: {ledger.runs.for_task('arceus-blog')[-1].status.value}")

        _log("")
        _log("=" * 72)
        _log("RESULT")
        _log(f"   task status: {ledger.tasks.get('arceus-blog').status.value}")  # type: ignore[union-attr]
        _verify_strapi(before)
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
