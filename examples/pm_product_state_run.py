"""Keyed e2e — the PM grounds a decision on PRODUCT STATE, not just the web (pm design doc §03 input ①).

Seeds a mini Arceus workspace with a couple of real source files and a small ``warehouse.db``
(``run_metrics`` by week), hires the PM, and runs one decision beat. The point is the two product-state
tools now on the PM's shelf:

    repo_search      — read the codebase: what's already shipped, is the change feasible?
    warehouse_query  — read the local SQL warehouse: did the metric actually move / is this the gap?

The run logs every product-state read and the recorded decision, then dumps whether the decision cites
an INTERNAL fact (a repo path or a warehouse metric) alongside any web sources — the whole reason the
PM reaches inward before it decides.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/pm_product_state_run.py

Skips cleanly (exit 0) when those env vars are unset. Tavily (TAVILY_API_KEY) is optional here — the
decision can be grounded on product state alone; web_search just adds external corroboration.
"""

from __future__ import annotations

import asyncio
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import sqlite3
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
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

# --- The product context: the same "what to build next" decision, but the PM must look inward first. ---
_TASK = (
    "You are the product manager for Arceus (arceus.sh), an autonomous AI-company product. Decide what "
    "to build next: (a) live run presence/activity indicators, (b) a second LLM provider, or (c) a "
    "marketing site refresh.\n\n"
    "Ground the decision in the PRODUCT'S OWN STATE first, then the outside world:\n"
    "1. `repo_search` the codebase to see what already exists and whether the bet is feasible (search "
    "for terms like 'run', 'status', 'presence', 'provider').\n"
    "2. `warehouse_query` the local warehouse for the metric that says whether this is the real gap — "
    "discover the schema with `SELECT name FROM sqlite_master WHERE type='table'` then read "
    "`run_metrics` (weekly run_completion_rate and stuck_tickets).\n"
    "3. Optionally corroborate with one `web_search`.\n"
    "Then RECORD the decision with the `record_decision` tool — its `claims` MUST include at least one "
    "INTERNAL fact (cite the repo path you found it in, e.g. `repo:app/run_status.py`, or the warehouse "
    "metric, e.g. `warehouse:run_metrics`). Finally write plan.md with a `## Decision` section."
)

# Files seeded into the product repo — enough for repo_search to find real, decision-relevant hits.
_SEED_FILES: dict[str, str] = {
    "README.md": (
        "# Arceus\nYour AI company, running autonomously. Core loop: plan -> code -> test -> ship.\n"
        "Runs are currently opaque between 'started' and 'shipped'.\n"
    ),
    "app/run_status.py": (
        '"""Run lifecycle state (backend only — no live UI surface yet)."""\n\n'
        "STATES = ['queued', 'running', 'shipped', 'failed']\n\n\n"
        "def current_state(run):\n"
        "    # There is no presence/activity feed yet: the UI only reads this terminal state.\n"
        "    return run.get('state', 'queued')\n"
    ),
    "app/providers.py": (
        '"""LLM provider wiring — a single provider today."""\n\n'
        "PROVIDERS = ['primary']  # no redundancy / second provider yet\n"
    ),
}

# The local warehouse: a flat run-completion rate + a rising stuck-ticket count — the quantitative gap.
_WAREHOUSE_ROWS = [
    ("2026-06-08", 0.62, 41),
    ("2026-06-15", 0.61, 47),
    ("2026-06-22", 0.63, 52),
    ("2026-06-29", 0.62, 58),
]


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class _Bus(EventBus):
    """Print the product-state reads + the decision so the inward-reach is visible."""

    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.tools: list[str] = []

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            tool = str(p.get("tool", "?"))
            self.tools.append(tool)
            if tool in ("repo_search", "warehouse_query", "web_search", "record_decision"):
                _log(f"    -> TOOL {tool}  {str(p.get('input', ''))[:120]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT and p.get("tool") in (
            "repo_search",
            "warehouse_query",
        ):
            _log(
                f"    <- {p.get('tool')}  {str(p.get('content', ''))[:160].splitlines()[0] if p.get('content') else ''}"
            )
        elif event.kind is EventKind.RUN_EVALUATED:
            _log(f"    |- evaluated: {p.get('outcome', p)}")


def _seed_repo(path: Path) -> None:
    """A minimal but real product repo: source files + a warehouse.db, committed so the worktree gets them."""
    path.mkdir(parents=True)
    for rel, body in _SEED_FILES.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _seed_warehouse(path / "warehouse.db")
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
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
            "seed",
        ],
        check=True,
        capture_output=True,
    )


def _seed_warehouse(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE run_metrics (week TEXT PRIMARY KEY, run_completion_rate REAL, stuck_tickets INTEGER)"
        )
        conn.executemany("INSERT INTO run_metrics VALUES (?, ?, ?)", _WAREHOUSE_ROWS)
        conn.commit()
    finally:
        conn.close()


def _is_internal(source_url: str) -> bool:
    """A product-state citation, not a web URL — a repo path or a warehouse reference."""
    u = source_url.lower()
    return not u.startswith(("http://", "https://")) or "repo:" in u or "warehouse" in u


def main() -> int:
    key, base, dep = (
        os.environ.get(k)
        for k in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_DEPLOYMENT")
    )
    if not (key and base and dep):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    root = Path(tempfile.mkdtemp(prefix="pm-product-state-"))
    os.chdir(root)
    seed = root / "source"
    _seed_repo(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    bus = _Bus()
    try:
        reg = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=key,
            base_url=base,
            deployment=dep,
            company_id="arceus",
            roles=reg,
            pricing=default_pricing_from_env(),
            seed=seed,
            ledger=ledger,
        )
        ledger.employees.create(Employee(id="piper", name="Piper", role="pm"))
        mat = factory.materialize(ledger.employees.get("piper"))  # type: ignore[arg-type]
        _log("=" * 72)
        _log("PM materialized — product-state tools now on the shelf:")
        _log(f"   {', '.join(t for t in mat.config.tools)}")
        _log(
            f"   seeded product files: {', '.join(sorted(_SEED_FILES))} + warehouse.db (run_metrics)"
        )

        ledger.tasks.submit(Task(id="arceus-next", intent=_TASK))
        assign_task(ledger, "arceus-next", "piper")
        sched = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="arceus"),
            roles=reg,
            landers=default_landers(factory.company_root, ledger=ledger),
            event_bus=bus,
            max_concurrent_runs=1,
            lease_ttl_s=1200.0,
        )
        for n in range(1, 4):
            t = ledger.tasks.get("arceus-next")
            if t is None or t.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
                break
            _log(f"\n[tick {n}]")
            asyncio.run(_pulse(sched))
            run = ledger.runs.for_task("arceus-next")[-1]
            dod = ledger.dod.get_for_task("arceus-next")
            _log(f"   run: {run.status.value}   DoD: {dod.status.value if dod else '-'}")

        _log("\n" + "=" * 72)
        _log("RESULT")
        _log(f"   task status         : {ledger.tasks.get('arceus-next').status.value}")  # type: ignore[union-attr]
        _log(
            f"   repo_search calls   : {bus.tools.count('repo_search')}   "
            f"warehouse_query calls: {bus.tools.count('warehouse_query')}   "
            f"record_decision calls: {bus.tools.count('record_decision')}"
        )
        decisions = ledger.decisions.for_task("arceus-next")
        if decisions:
            claims = ledger.claims.for_decisions([decisions[0].id])
            internal = [c for c in claims if _is_internal(c.source_url)]
            _log(
                f"   decision            : {decisions[0].option!r} @ confidence {decisions[0].confidence}"
            )
            _log(f"   cited sources       : {[c.source_url for c in claims]}")
            _log(f"   >>> cites PRODUCT STATE (internal source): {bool(internal)}")
            for c in internal:
                _log(f"       - {c.source_url}: {c.text[:100]}")
        else:
            _log("   no decision recorded")
        return 0
    finally:
        ledger.close()


async def _pulse(sched: Scheduler) -> None:
    await sched.tick_once()
    await sched.drain()


if __name__ == "__main__":
    raise SystemExit(main())
