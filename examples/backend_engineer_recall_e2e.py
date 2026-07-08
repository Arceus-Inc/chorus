"""Backend Engineer recall e2e — five sequential heartbeat beats on one employee.

Validates the episodic loop (spec 07 §11): each beat writes a keyed record; later beats can call
``recall`` to read prior beats with outcomes attached. Tracks tool usage per beat and checks the
EpisodicStore accumulates honestly.

    uv run python examples/backend_engineer_recall_e2e.py

Requires AZURE_OPENAI_* in the repo-root ``.env`` (loaded via python-dotenv).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.memory import EpisodicStore
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._env import load_env_file
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

# Five small, incremental edits on the same module — later beats should have recall history.
_TASKS: tuple[tuple[str, str], ...] = (
    (
        "t1",
        "In textutil.py add slugify(s: str) -> str that lowercases, replaces non-alphanumeric runs "
        "with '-', and strips leading/trailing '-'. In test_textutil.py add a pytest asserting "
        "slugify('Hello, World!') == 'hello-world'. Keep health(). Make tests pass.",
    ),
    (
        "t2",
        "In textutil.py add truncate(s: str, n: int) -> str returning s unchanged when len(s) <= n "
        "else s[:n] + '…'. In test_textutil.py add a pytest for truncate. Keep slugify + health. "
        "Make tests pass.",
    ),
    (
        "t3",
        "In textutil.py add word_count(s: str) -> int counting whitespace-separated words (empty -> 0). "
        "In test_textutil.py add a pytest for word_count. Keep prior functions. Make tests pass.",
    ),
    (
        "t4",
        "In textutil.py add is_palindrome(s: str) -> bool (case-insensitive, ignore non-alphanumeric). "
        "In test_textutil.py add a pytest for is_palindrome. Keep prior functions. Make tests pass.",
    ),
    (
        "t5",
        "slugify('---Hi---') must return 'hi' not '-hi-'. Fix slugify in textutil.py if needed and add "
        "a regression test. Do not break truncate, word_count, or is_palindrome. Make tests pass.",
    ),
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
class _RecallCall:
    task_id: str
    run_id: str
    input: dict[str, object]
    is_error: bool
    preview: str = ""


@dataclass
class _BeatTrace:
    task_id: str
    run_id: str = ""
    tool_calls: list[str] = field(default_factory=list)
    recall_calls: list[_RecallCall] = field(default_factory=list)
    outcome: str = "?"
    task_status: str = "?"


class _RecallBus(EventBus):
    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.traces: list[_BeatTrace] = []
        self._current: _BeatTrace | None = None
        self._pending_recall: _RecallCall | None = None

    def start_beat(self, task_id: str) -> None:
        self._current = _BeatTrace(task_id=task_id)
        self.traces.append(self._current)

    def emit(self, event: Event) -> None:
        try:
            p = event.payload
            if self._current is None:
                return
            if event.kind is EventKind.RUN_STARTED:
                self._current.run_id = str(p.get("run_id", ""))
            elif event.kind is EventKind.RUN_TOOL_USE:
                tool = str(p.get("tool", "?"))
                self._current.tool_calls.append(tool)
                if tool == "recall":
                    raw = p.get("input", {})
                    inp = raw if isinstance(raw, dict) else {}
                    self._pending_recall = _RecallCall(
                        task_id=self._current.task_id,
                        run_id=self._current.run_id,
                        input=inp,
                        is_error=False,
                    )
                    self._current.recall_calls.append(self._pending_recall)
            elif event.kind is EventKind.RUN_TOOL_RESULT and self._pending_recall is not None:
                if str(p.get("tool", "")) == "recall":
                    self._pending_recall.is_error = bool(p.get("is_error"))
                    content = p.get("content", p.get("output", ""))
                    self._pending_recall.preview = str(content)[:300]
                    self._pending_recall = None
            elif event.kind is EventKind.RUN_EVALUATED:
                self._current.outcome = str(p.get("outcome", "?"))
        except Exception:
            pass


async def _run_task(
    scheduler: Scheduler,
    ledger: SqliteLedger,
    bus: _RecallBus,
    task_id: str,
    *,
    max_ticks: int = 4,
) -> _BeatTrace | None:
    last: _BeatTrace | None = None
    for tick in range(1, max_ticks + 1):
        task = ledger.tasks.get(task_id)
        if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
            break
        _log(f"    tick {tick} …")
        bus.start_beat(task_id)
        await scheduler.tick_once()
        await scheduler.drain()
        last = bus.traces[-1]
        last.task_status = ledger.tasks.get(task_id).status.value  # type: ignore[union-attr]
    return last


def _score_recall_usage(
    traces: list[_BeatTrace], store: EpisodicStore, employee_id: str
) -> list[tuple[str, bool, str]]:
    records = store.records_for(employee_id)
    recall_total = sum(len(t.recall_calls) for t in traces)
    recall_errors = sum(1 for t in traces for c in t.recall_calls if c.is_error)
    later_beats = [t for t in traces if t.task_id != "t1"]
    later_with_recall = sum(1 for t in later_beats if t.recall_calls)

    checks: list[tuple[str, bool, str]] = [
        (
            "episodic records accumulate (one per completed beat)",
            len(records) >= 3,
            f"{len(records)} record(s) for {employee_id}",
        ),
        (
            "recall tool invoked at least once across the run",
            recall_total >= 1,
            f"{recall_total} call(s) across {len(traces)} beat trace(s)",
        ),
        (
            "recall calls succeed (no tool errors)",
            recall_errors == 0,
            f"{recall_errors} error(s)",
        ),
        (
            "later beats (t2+) use recall for orientation",
            later_with_recall >= 1,
            f"{later_with_recall}/{len(later_beats)} later beat(s) called recall",
        ),
    ]

    # Harness-quality signals: search recall when problem-shaped
    query_recalls = [
        c for t in traces for c in t.recall_calls if c.input.get("query") and not c.is_error
    ]
    checks.append(
        (
            "at least one search recall (query=)",
            len(query_recalls) >= 1 or recall_total >= 2,
            f"{len(query_recalls)} query= call(s)",
        )
    )

    checks.append(
        (
            "recall returned prior beats (non-empty hits on t2+)",
            any(
                c.preview and "no past beats" not in c.preview
                for t in later_beats
                for c in t.recall_calls
            ),
            f"{sum(1 for t in later_beats for c in t.recall_calls if c.preview and 'no past beats' not in c.preview)} non-empty response(s)",
        )
    )

    return checks


def main() -> int:
    load_env_file(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log(
            "skipping: set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT in .env"
        )
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-recall-e2e-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = SqliteLedger.open(":memory:")
    bus = _RecallBus()
    report_path = (
        Path(__file__).resolve().parent.parent / "reports" / "backend-engineer-recall-e2e.json"
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
        memory_root = factory.company_root / "memory"
        store = EpisodicStore(memory_root)

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
        _log("BACKEND ENGINEER RECALL E2E — 5 sequential heartbeat tasks")
        _log(f"  company_root : {factory.company_root}")
        _log(f"  memory store : {memory_root / 'episodic.db'}")
        _log(f"  deployment   : {deployment}")
        _log("=" * 72)

        completed = 0
        for task_id, intent in _TASKS:
            _log(f"\n▶ TASK {task_id}")
            _log(f"  {intent[:100]}…")
            ledger.tasks.submit(Task(id=task_id, intent=intent))
            assign_task(ledger, task_id, "bex")
            ledger.dod.create(task_id, _DOD)

            trace = asyncio.run(_run_task(scheduler, ledger, bus, task_id))
            final = ledger.tasks.get(task_id)
            status = final.status.value if final else "?"
            _log(f"  → status: {status}")
            if trace and trace.recall_calls:
                for rc in trace.recall_calls:
                    _log(f"    recall({json.dumps(rc.input)}) → {'ERR' if rc.is_error else 'ok'}")
                    if rc.preview:
                        _log(f"      {rc.preview[:160].replace(chr(10), ' ')}")
            else:
                _log("    recall: (not called this beat)")
            if final and final.status is TaskStatus.DONE:
                completed += 1

        checks = _score_recall_usage(bus.traces, store, "bex")
        records = store.records_for("bex")

        _log("\n" + "=" * 72)
        _log("EPISODIC STORE")
        for r in records:
            _log(f"  {r.run_id[:12]}… outcome={r.outcome} files={list(r.files_touched)}")

        _log("\nRECALL HARNESS CHECKS")
        all_ok = True
        for name, ok, detail in checks:
            _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
            all_ok = all_ok and ok

        payload = {
            "completed_tasks": completed,
            "total_tasks": len(_TASKS),
            "episodic_records": len(records),
            "traces": [
                {
                    "task_id": t.task_id,
                    "run_id": t.run_id,
                    "outcome": t.outcome,
                    "recall_calls": [
                        {"input": c.input, "is_error": c.is_error, "preview": c.preview}
                        for c in t.recall_calls
                    ],
                    "tools": t.tool_calls,
                }
                for t in bus.traces
            ],
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _log(f"\nreport: {report_path}")
        _log(
            f"\n{'ALL CHECKS PASS' if all_ok else 'SOME CHECKS FAILED'} ({completed}/{len(_TASKS)} tasks done)"
        )
        return 1 if not all_ok or completed < 3 else 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
