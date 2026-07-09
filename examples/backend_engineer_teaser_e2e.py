"""Backend Engineer episodic teaser e2e — two beats, beat-start push (R6).

Beat 1 writes episodic memory; beat 2 materializes with an auto teaser in the harness brief.
Checks the teaser file deterministically and probes whether the agent references prior work.

    uv run python examples/backend_engineer_teaser_e2e.py

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
class _BeatTrace:
    task_id: str
    run_id: str = ""
    tool_calls: list[str] = field(default_factory=list)
    recall_calls: int = 0
    role_texts: list[str] = field(default_factory=list)
    outcome: str = "?"
    task_status: str = "?"


class _TeaserBus(EventBus):
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
            p = event.payload
            if event.kind is EventKind.RUN_STARTED:
                self._current.run_id = str(p.get("run_id", ""))
            elif event.kind is EventKind.RUN_TOOL_USE:
                tool = str(p.get("tool", "?"))
                self._current.tool_calls.append(tool)
                if tool == "recall":
                    self._current.recall_calls += 1
            elif event.kind is EventKind.RUN_TEXT:
                text = str(p.get("text", p.get("content", "")))
                if text.strip():
                    self._current.role_texts.append(text)
            elif event.kind is EventKind.RUN_EVALUATED:
                self._current.outcome = str(p.get("outcome", "?"))
        except Exception:
            pass


async def _run_task(
    scheduler: Scheduler,
    ledger: SqliteLedger,
    bus: _TeaserBus,
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


def _mentions_slugify(text: str) -> bool:
    lower = text.lower()
    return "slugify" in lower or "slug" in lower


def _score_teaser(
    *,
    store: EpisodicStore,
    employee_id: str,
    teaser_path: Path,
    t2_trace: _BeatTrace | None,
) -> list[tuple[str, bool, str]]:
    records = store.records_for(employee_id)
    checks: list[tuple[str, bool, str]] = [
        (
            "beat 1 wrote episodic memory",
            len(records) >= 1,
            f"{len(records)} record(s)",
        ),
        (
            "beat 2 harness has episodic-beat-start.json",
            teaser_path.is_file(),
            str(teaser_path),
        ),
    ]
    teaser_text = teaser_path.read_text(encoding="utf-8") if teaser_path.is_file() else ""
    checks.append(
        (
            "teaser mentions slugify from beat 1",
            "slugify" in teaser_text.lower(),
            teaser_text[:160].replace("\n", " "),
        )
    )
    if t2_trace is not None:
        joined_text = "\n".join(t2_trace.role_texts)
        text_before_recall = (_mentions_slugify(joined_text) and t2_trace.recall_calls == 0) or (
            t2_trace.recall_calls > 0 and any(_mentions_slugify(t) for t in t2_trace.role_texts[:1])
        )
        checks.append(
            (
                "beat 2 agent references prior slugify work (soft)",
                text_before_recall or _mentions_slugify(joined_text),
                f"recall_calls={t2_trace.recall_calls}, texts={len(t2_trace.role_texts)}",
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

    base = Path(tempfile.mkdtemp(prefix="chorus-teaser-e2e-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = SqliteLedger.open(":memory:")
    bus = _TeaserBus()
    report_path = (
        Path(__file__).resolve().parent.parent / "reports" / "backend-engineer-teaser-e2e.json"
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
        _log("BACKEND ENGINEER TEASER E2E — 2 sequential beats (R6)")
        _log(f"  company_root : {factory.company_root}")
        _log(f"  memory store : {memory_root / 'episodic.db'}")
        _log("=" * 72)

        task_id, intent = _TASKS[0]
        _log(f"\n▶ TASK {task_id}")
        _log(f"  {intent[:100]}…")
        ledger.tasks.submit(Task(id=task_id, intent=intent))
        assign_task(ledger, task_id, "bex")
        ledger.dod.create(task_id, _DOD)
        asyncio.run(_run_task(scheduler, ledger, bus, task_id))
        final = ledger.tasks.get(task_id)
        _log(f"  → status: {final.status.value if final else '?'}")

        pre_mat = factory.materialize(
            Employee(id="bex", name="Bex", role="backend_engineer"),
            task_id="t2",
        )
        teaser_path = pre_mat.working_dir / ".harness" / "episodic-beat-start.json"

        task_id, intent = _TASKS[1]
        _log(f"\n▶ TASK {task_id}")
        _log(f"  {intent[:100]}…")
        ledger.tasks.submit(Task(id=task_id, intent=intent))
        assign_task(ledger, task_id, "bex")
        ledger.dod.create(task_id, _DOD)
        asyncio.run(_run_task(scheduler, ledger, bus, task_id))
        final = ledger.tasks.get(task_id)
        _log(f"  → status: {final.status.value if final else '?'}")

        t2_trace = next((t for t in bus.traces if t.task_id == "t2"), None)
        checks = _score_teaser(
            store=store,
            employee_id="bex",
            teaser_path=teaser_path,
            t2_trace=t2_trace,
        )

        _log("\nTEASER CHECKS")
        all_ok = True
        for name, ok, detail in checks:
            _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
            all_ok = all_ok and ok

        payload = {
            "episodic_records": len(store.records_for("bex")),
            "teaser_path": str(teaser_path),
            "teaser": teaser_path.read_text(encoding="utf-8") if teaser_path.is_file() else "",
            "traces": [
                {
                    "task_id": t.task_id,
                    "run_id": t.run_id,
                    "recall_calls": t.recall_calls,
                    "role_text_snippets": [s[:200] for s in t.role_texts[:5]],
                }
                for t in bus.traces
            ],
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
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
