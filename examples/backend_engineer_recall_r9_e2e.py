"""Backend Engineer recall R9 e2e — debug profile rerank (R9-0).

Two real-agent beats plus deterministic checks for ``profile='debug'`` rerank,
refusal without scope, and structured observations (profile echo, rank_note).

    uv run python examples/backend_engineer_recall_r9_e2e.py

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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dream.tools._context import ToolExecutionContext

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import BeatContext, Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.memory import EpisodicStore, SprintDelta
from chorus.memory._recall_service import EpisodicRecallService
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._env import load_env_file
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory
from chorus_tools._recall import RecallTool

_T1 = (
    "t1",
    "In textutil.py add slugify(s: str) -> str that lowercases, replaces non-alphanumeric runs "
    "with '-', and strips leading/trailing '-'. In test_textutil.py add a pytest asserting "
    "slugify('Hello, World!') == 'hello-world'. Keep health(). Make tests pass.",
)

_T2 = (
    "t2",
    "FIRST: call recall(query='slugify', profile='debug') to surface any prior slugify failures "
    "on this thread; use get_run(run_id=…) on the top hit if useful. "
    "THEN add truncate(s: str, n: int) -> str returning s unchanged when len(s) <= n "
    "else s[:n] + '…'. Keep slugify + health. Make tests pass.",
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


def _role_text(text: str) -> str:
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _inject_prior_failure(store: EpisodicStore, *, before: datetime) -> str:
    """Simulate an earlier failed slugify attempt on t1 — gives debug rerank a failure to promote."""
    run_id = "r_fixture_fail"
    store.append(
        SprintDelta(
            run_id=run_id,
            task_id="t1",
            employee_id="bex",
            scope="project",
            intent="slugify regression — strip edge case wrong",
            outcome="needs_changes",
            score=0.0,
            created_at=before,
            role="backend_engineer",
            recorded_at=before,
            files_touched=("textutil.py", "test_textutil.py"),
            body=_role_text(
                "tried slugify without stripping leading/trailing dashes; tests failed"
            ),
        )
    )
    return run_id


@dataclass
class _ToolCall:
    tool: str
    input: dict[str, object]


@dataclass
class _BeatTrace:
    task_id: str
    run_id: str = ""
    outcome: str = "?"
    tool_calls: list[_ToolCall] = field(default_factory=list)


class _RecallR9Bus(EventBus):
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
    bus: _RecallR9Bus,
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


async def _deterministic_r9_checks(
    store: EpisodicStore,
    working_dir: Path,
    *,
    fixture_run_id: str,
) -> list[tuple[str, bool, str]]:
    svc = EpisodicRecallService(store)
    ctx = ToolExecutionContext(working_dir=working_dir, session_id="det")
    BeatContext(task_id="t2", run_id="r_det", employee_id="bex").write(working_dir)
    tool = RecallTool(svc)

    refuse = await tool.execute({"profile": "debug"}, ctx)
    refuse_ok = refuse.is_error is True and "task_id" in refuse.content.lower()

    debug = await tool.execute({"query": "slugify regression", "profile": "debug"}, ctx)
    debug_struct = debug.structured or {}
    debug_hits = debug_struct.get("hits", [])
    debug_top = debug_hits[0] if debug_hits else {}
    debug_ok = (
        debug.is_error is False
        and debug_struct.get("profile") == "debug"
        and debug_top.get("run_id") == fixture_run_id
        and debug_top.get("outcome") == "needs_changes"
        and "rank_note" in debug_top
    )

    general = await tool.execute({"query": "slugify", "profile": "general"}, ctx)
    general_struct = general.structured or {}
    general_hits = general_struct.get("hits", [])
    general_top = general_hits[0] if general_hits else {}
    general_ok = (
        general.is_error is False
        and general_struct.get("profile") == "general"
        and all("rank_note" not in hit for hit in general_hits)
        and not any("failed previously" in str(a) for a in general_struct.get("next_actions", []))
    )

    task_debug = await tool.execute({"task_id": "t1", "profile": "debug"}, ctx)
    task_struct = task_debug.structured or {}
    task_ids = [str(hit.get("run_id")) for hit in task_struct.get("hits", [])]
    task_ok = task_debug.is_error is False and len(task_ids) > 0 and task_ids[0] == fixture_run_id

    recovery = debug_struct.get("next_actions", [])
    recovery_ok = any("failed previously" in str(action) for action in recovery)

    return [
        ("debug without scope refused", refuse_ok, refuse.content[:72]),
        (
            "debug query promotes fixture failure",
            debug_ok,
            str(debug_top.get("run_id", "?"))[:12],
        ),
        (
            "general response omits debug rank annotations",
            general_ok,
            f"top={str(general_top.get('run_id', '?'))[:12]}",
        ),
        (
            "debug task thread surfaces failure first",
            task_ok,
            str(task_ids[:2]),
        ),
        ("debug top failure adds recovery next_action", recovery_ok, str(recovery[:1])),
    ]


def _agent_r9_checks(traces: list[_BeatTrace]) -> list[tuple[str, bool, str]]:
    t2 = next((t for t in traces if t.task_id == "t2"), None)
    if t2 is None:
        return [("beat t2 ran", False, "missing trace")]
    recall_calls = [c for c in t2.tool_calls if c.tool == "recall"]
    debug_calls = [c for c in recall_calls if c.input.get("profile") == "debug"]
    return [
        (
            "agent called recall on beat 2",
            len(recall_calls) >= 1,
            f"{len(recall_calls)} recall call(s)",
        ),
        (
            "agent used recall(profile='debug')",
            len(debug_calls) >= 1,
            str([c.input for c in recall_calls]),
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

    base = Path(tempfile.mkdtemp(prefix="chorus-recall-r9-e2e-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = SqliteLedger.open(":memory:")
    bus = _RecallR9Bus()
    report_path = (
        Path(__file__).resolve().parent.parent / "reports" / "backend-engineer-recall-r9-e2e.json"
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
        _log("BACKEND ENGINEER RECALL R9 E2E — profile=debug rerank")
        _log("=" * 72)

        _log("\n▶ TASK t1")
        ledger.tasks.submit(Task(id="t1", intent=_T1[1]))
        assign_task(ledger, "t1", "bex")
        ledger.dod.create("t1", _DOD)
        asyncio.run(_run_task(scheduler, ledger, bus, "t1"))
        t1_final = ledger.tasks.get("t1")
        _log(f"  → status: {t1_final.status.value if t1_final else '?'}")

        fixture_ts = datetime.now(tz=UTC) - timedelta(days=2)
        fixture_run_id = _inject_prior_failure(store, before=fixture_ts)
        _log(f"  → injected prior failure fixture {fixture_run_id[:12]}…")

        _log("\n▶ TASK t2")
        ledger.tasks.submit(Task(id="t2", intent=_T2[1]))
        assign_task(ledger, "t2", "bex")
        ledger.dod.create("t2", _DOD)
        asyncio.run(_run_task(scheduler, ledger, bus, "t2"))
        t2_final = ledger.tasks.get("t2")
        _log(f"  → status: {t2_final.status.value if t2_final else '?'}")

        mat = factory.materialize(
            Employee(id="bex", name="Bex", role="backend_engineer"), task_id="t2"
        )
        det_checks = asyncio.run(
            _deterministic_r9_checks(store, mat.working_dir, fixture_run_id=fixture_run_id)
        )
        agent_checks = _agent_r9_checks(bus.traces)
        checks = det_checks + agent_checks

        _log("\nRECALL R9 CHECKS")
        all_ok = True
        for name, ok, detail in checks:
            _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
            all_ok = all_ok and ok

        payload = {
            "episodic_records": len(store.records_for("bex")),
            "fixture_run_id": fixture_run_id,
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
            "traces": [
                {
                    "task_id": t.task_id,
                    "run_id": t.run_id,
                    "outcome": t.outcome,
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
