"""Backend Engineer recall v2 e2e — teaser + filters + get_run (R6–R8).

Two real-agent beats plus deterministic tool checks for recall filters and get_run drill-down.

    uv run python examples/backend_engineer_recall_v2_e2e.py

Requires AZURE_OPENAI_* in the repo-root ``.env``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import BeatContext, Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.memory import EpisodicStore
from chorus.memory._recall_service import EpisodicRecallService
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._env import load_env_file
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory
from chorus_tools._get_run import GetRunTool
from chorus_tools._recall import RecallTool
from dream.tools._context import ToolExecutionContext

_T1 = (
    "t1",
    "In textutil.py add slugify(s: str) -> str that lowercases, replaces non-alphanumeric runs "
    "with '-', and strips leading/trailing '-'. In test_textutil.py add a pytest asserting "
    "slugify('Hello, World!') == 'hello-world'. Keep health(). Make tests pass.",
)

_T2 = (
    "t2",
    "FIRST: call recall(task_id='t1') to see your prior slugify beat, then get_run(run_id=…) "
    "on the first hit for full detail. THEN add truncate(s: str, n: int) -> str returning s "
    "unchanged when len(s) <= n else s[:n] + '…'. Keep slugify + health. Make tests pass.",
)

_DOD = Verifier.command(
    "test -f test_evidence/manifest.json && "
    'grep -q \'"verdict": "pass"\' test_evidence/manifest.json',
    artifact_class="pr",
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "textutil.py").write_text('def health() -> str:\n    return "ok"\n', encoding="utf-8")
    (path / "test_textutil.py").write_text(
        'from textutil import health\n\n\ndef test_health() -> None:\n    assert health() == "ok"\n',
        encoding="utf-8",
    )
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
            "-qm",
            "init",
        ],
        check=True,
        capture_output=True,
    )


@dataclass
class _ToolCall:
    tool: str
    input: dict[str, object]


@dataclass
class _BeatTrace:
    task_id: str
    run_id: str = ""
    tool_calls: list[_ToolCall] = field(default_factory=list)
    outcome: str = "?"


class _RecallV2Bus(EventBus):
    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.traces: list[_BeatTrace] = []
        self._current: _BeatTrace | None = None

    def start_beat(self, task_id: str) -> None:
        self._current = _BeatTrace(task_id=task_id)
        self.traces.append(self._current)

    def emit(self, event: Event) -> None:
        try:
            if self._current is None:
                return
            payload = event.payload
            if event.kind is EventKind.RUN_STARTED:
                self._current.run_id = str(payload.get("run_id", ""))
            elif event.kind is EventKind.RUN_TOOL_USE:
                raw = payload.get("input", {})
                inp = raw if isinstance(raw, dict) else {}
                self._current.tool_calls.append(
                    _ToolCall(tool=str(payload.get("tool", "?")), input=inp)
                )
            elif event.kind is EventKind.RUN_EVALUATED:
                self._current.outcome = str(payload.get("outcome", "?"))
        except Exception:
            pass


async def _run_task(
    scheduler: Scheduler,
    ledger: SqliteLedger,
    bus: _RecallV2Bus,
    task_id: str,
    *,
    max_ticks: int = 4,
) -> None:
    for tick in range(1, max_ticks + 1):
        task = ledger.tasks.get(task_id)
        if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
            break
        _log(f"    tick {tick} …")
        bus.start_beat(task_id)
        await scheduler.tick_once()
        await scheduler.drain()


async def _deterministic_tool_checks(
    store: EpisodicStore,
    working_dir: Path,
) -> list[tuple[str, bool, str]]:
    svc = EpisodicRecallService(store)
    ctx = ToolExecutionContext(working_dir=working_dir, session_id="det")
    BeatContext(task_id="t2", run_id="r_det", employee_id="bex").write(working_dir)

    filter_result = await RecallTool(svc).execute({"task_id": "t1", "limit": 3}, ctx)
    filter_hits = (filter_result.structured or {}).get("hits", [])
    filter_ok = (
        filter_result.is_error is False
        and isinstance(filter_hits, list)
        and len(filter_hits) >= 1
        and "slugify" in str(filter_hits[0].get("intent", "")).lower()
    )
    first_run_id = str(filter_hits[0]["run_id"]) if filter_hits else ""
    get_result = (
        await GetRunTool(svc).execute({"run_id": first_run_id}, ctx) if first_run_id else None
    )
    get_ok = (
        get_result is not None
        and get_result.is_error is False
        and "slugify" in get_result.content.lower()
    )

    return [
        (
            "recall(task_id=t1) returns slugify hit(s)",
            filter_ok,
            f"{len(filter_hits) if isinstance(filter_hits, list) else 0} hit(s)",
        ),
        (
            "get_run returns full prose for filtered hit",
            get_ok,
            first_run_id[:12] if first_run_id else "(no run_id)",
        ),
        (
            "recall hits are slim (summary, no prose field)",
            bool(filter_hits)
            and isinstance(filter_hits[0], dict)
            and "summary" in filter_hits[0]
            and "prose" not in filter_hits[0],
            "slim schema",
        ),
    ]


def _agent_tool_checks(traces: list[_BeatTrace]) -> list[tuple[str, bool, str]]:
    t2 = next((t for t in traces if t.task_id == "t2"), None)
    if t2 is None:
        return [("beat t2 ran", False, "missing trace")]
    recall_calls = [c for c in t2.tool_calls if c.tool == "recall"]
    get_calls = [c for c in t2.tool_calls if c.tool == "get_run"]
    task_filter = any(c.input.get("task_id") == "t1" for c in recall_calls)
    return [
        (
            "agent called recall on beat 2",
            len(recall_calls) >= 1,
            f"{len(recall_calls)} recall call(s)",
        ),
        (
            "agent used recall(task_id=t1)",
            task_filter,
            str([c.input for c in recall_calls]),
        ),
        (
            "agent called get_run on beat 2",
            len(get_calls) >= 1,
            f"{len(get_calls)} get_run call(s)",
        ),
    ]


def main() -> int:
    load_env_file(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_* in .env")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-recall-v2-e2e-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = SqliteLedger.open(":memory:")
    bus = _RecallV2Bus()
    report_path = (
        Path(__file__).resolve().parent.parent / "reports" / "backend-engineer-recall-v2-e2e.json"
    )

    try:
        registry = RoleRegistry.from_plugins(default_roles())
        factory = EmployeeHarnessFactory(
            api_key=api_key,
            base_url=base_url,
            deployment=deployment,
            company_id="acme",
            roles=registry,
            pricing=default_pricing_from_env(),
            seed=seed,
        )
        store = EpisodicStore(factory.company_root / "memory")
        ledger.employees.create(Employee(id="bex", name="Bex", role="backend_engineer"))
        scheduler = Scheduler(
            ledger=ledger,
            workforce=LedgerWorkforce(ledger.employees),
            beat_runner_for=factory,
            budget_enforcer=BudgetEnforcer(ledger, company_id="acme"),
            roles=registry,
            landers=default_landers(factory.company_root),
            memory_writer=store,
            event_bus=bus,
            max_concurrent_runs=1,
        )

        _log("=" * 72)
        _log("BACKEND ENGINEER RECALL V2 E2E — teaser + filters + get_run")
        _log("=" * 72)

        for task_id, intent in (_T1, _T2):
            _log(f"\n▶ TASK {task_id}")
            ledger.tasks.submit(Task(id=task_id, intent=intent))
            assign_task(ledger, task_id, "bex")
            ledger.dod.create(task_id, _DOD)
            asyncio.run(_run_task(scheduler, ledger, bus, task_id))
            final = ledger.tasks.get(task_id)
            _log(f"  → status: {final.status.value if final else '?'}")

        mat = factory.materialize(
            Employee(id="bex", name="Bex", role="backend_engineer"), task_id="t2"
        )
        det_checks = asyncio.run(_deterministic_tool_checks(store, mat.working_dir))
        agent_checks = _agent_tool_checks(bus.traces)
        checks = det_checks + agent_checks

        _log("\nRECALL V2 CHECKS")
        all_ok = True
        for name, ok, detail in checks:
            _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
            all_ok = all_ok and ok

        payload = {
            "episodic_records": len(store.records_for("bex")),
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
            "traces": [
                {
                    "task_id": t.task_id,
                    "run_id": t.run_id,
                    "tools": [{"tool": c.tool, "input": c.input} for c in t.tool_calls],
                }
                for t in bus.traces
            ],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _log(f"\nreport: {report_path}")
        _log(f"\n{'ALL CHECKS PASS' if all_ok else 'SOME CHECKS FAILED'}")
        return 0 if all_ok else 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
