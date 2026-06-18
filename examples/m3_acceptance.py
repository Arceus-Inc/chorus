"""Keyed M3 Slice 1 acceptance — the whole manager loop, end to end with a live model.

One manager + two engineers, through the real scheduler:

    manager beat → decompose([api→ada, ui→bob]) → PARK (parent waits on its subtree)
    → engineer beats build + land their children → children_done re-invokes the manager
    → INTEGRATE beat → Mechanical DoD (all children terminal) → parent done
    → ManagerLander records the `subtree` artifact

Run with live keys; writes a self-contained HTML report under ``reports/``. Skips (exit 0) when the
Azure env vars are unset. Bounded by a tick budget so a stuck engineer can't run forever.

    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_BASE_URL=... AZURE_OPENAI_DEPLOYMENT=...
    uv run python examples/m3_acceptance.py
"""

from __future__ import annotations

import asyncio
import html
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
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

_PARENT = (
    "Delegate this with a SINGLE decompose call containing EXACTLY two independent children (no more, "
    "no depends_on between them, do not implement anything yourself):\n"
    "- label 'add', assignee 'ada': In a new file add_util.py write exactly `def add(a, b):\\n    "
    "return a + b`. In test_add_util.py write `from add_util import add\\n\\n\\ndef test_add():\\n    "
    "assert add(1, 2) == 3`. Run pytest -q to confirm it passes.\n"
    "- label 'sub', assignee 'bob': In a new file sub_util.py write exactly `def subtract(a, b):\\n    "
    "return a - b`. In test_sub_util.py write `from sub_util import subtract\\n\\n\\ndef "
    "test_subtract():\\n    assert subtract(3, 1) == 2`. Run pytest -q to confirm it passes."
)

_LOG: list[str] = []


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()
    _LOG.append(msg)


class _Bus(EventBus):
    def __init__(self) -> None:
        super().__init__(log_path=None)

    def emit(self, event: Event) -> None:
        p = event.payload
        if event.kind is EventKind.RUN_TOOL_USE:
            _log(f"    → TOOL {p.get('tool', '?')}  {str(p.get('input', ''))[:140]}")
        elif event.kind is EventKind.RUN_TOOL_RESULT:
            tag = "ERR" if p.get("is_error") else "ok"
            note = f"  {str(p.get('content', ''))[:300]}" if p.get("is_error") else ""
            _log(f"    ← {p.get('tool', '?')} [{tag}]{note}")


def _seed_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# math utils\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.name=s", "-c", "user.email=s@x", "commit", "-m", "init"],
        check=True, capture_output=True,
    )


def _write_report(ledger: SqliteLedger, *, ok: bool) -> Path:
    rows = []
    parent = ledger.tasks.get("feature")
    for child in ledger.tasks.children("feature"):
        arts = ledger.artifacts.list_for_task(child.id)
        ref = arts[0].resource_ref if arts else {}
        rows.append(
            f"<tr><td>{html.escape(child.id)}</td><td>{html.escape(str(child.assignee_employee_id))}</td>"
            f"<td>{html.escape(child.status.value)}</td><td><code>{html.escape(str(ref))}</code></td></tr>"
        )
    subtree = next(
        (a for a in ledger.artifacts.list_for_task("feature")
         if a.resource_ref is not None and a.resource_ref.get("kind") == "subtree"), None,
    )
    verdict = "PASS ✅" if ok else "INCOMPLETE ⚠️"
    body = (
        f"<h1>M3 Slice 1 acceptance — {verdict}</h1>"
        f"<p>parent <code>feature</code> status: <b>{html.escape(parent.status.value) if parent else '?'}</b>"
        f" — subtree artifact recorded: <b>{'yes' if subtree else 'no'}</b></p>"
        "<h2>Children (the delegated subtree)</h2>"
        "<table border=1 cellpadding=6 style='border-collapse:collapse'>"
        "<tr><th>task</th><th>assignee</th><th>status</th><th>artifact</th></tr>"
        + "".join(rows) + "</table>"
        "<h2>Beat trace</h2><pre style='background:#111;color:#ddd;padding:12px'>"
        + html.escape("\n".join(_LOG)) + "</pre>"
    )
    out = Path(__file__).parent / "reports" / "m3_acceptance.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(f"<!doctype html><meta charset=utf-8><body>{body}</body>", encoding="utf-8")
    return out


def main() -> int:
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-m3acc-"))
    os.chdir(base)
    seed = base / "source"
    _seed_repo(seed)

    ledger = SqliteLedger.open(":memory:")
    try:
        from chorus.roles import RoleRegistry, default_roles

        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key, base_url=base_url, deployment=deployment, company_id="acme",
            roles=registry, pricing=default_pricing_from_env(), seed=seed, ledger=ledger,
        )
        ledger.employees.create(Employee(id="moe", name="Moe", role="manager"))
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        ledger.employees.create(Employee(id="bob", name="Bob", role="engineer"))
        ledger.tasks.submit(Task(id="feature", intent=_PARENT, status=TaskStatus.TODO))
        assign_task(ledger, "feature", "moe")

        scheduler = Scheduler(
            ledger=ledger, workforce=LedgerWorkforce(ledger.employees), beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="acme"), roles=registry,
            landers=default_landers(factory.company_root, ledger=ledger),
            event_bus=_Bus(), max_concurrent_runs=2,
        )

        async def _drive() -> None:
            for n in range(1, 13):  # bounded: decompose + 2 engineers (+ self-repair) + integrate
                parent = ledger.tasks.get("feature")
                if parent is not None and parent.status is TaskStatus.DONE:
                    break
                _log(f"\n=== TICK {n} ===")
                await scheduler.tick_once()
                await scheduler.drain()
                p = ledger.tasks.get("feature")
                kids = ledger.tasks.children("feature")
                _log(f"  parent={p.status.value if p else '?'}  "
                     f"children={[(c.id[-4:], c.status.value) for c in kids]}")

        asyncio.run(_drive())

        parent = ledger.tasks.get("feature")
        ok = parent is not None and parent.status is TaskStatus.DONE and ledger.tasks.all_children_terminal("feature")
        report = _write_report(ledger, ok=ok)
        _log("\n" + ("=" * 60))
        _log(f"parent status : {parent.status.value if parent else '?'}")
        _log(f"all children terminal: {ledger.tasks.all_children_terminal('feature')}")
        _log(f"report: {report}")
        _log("✅ ACCEPTANCE PASS" if ok else "⚠️ loop did not fully close (see report)")
        return 0 if ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
