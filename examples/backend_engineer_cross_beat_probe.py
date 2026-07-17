"""Cross-beat probe — Backend Engineer TODO.md + episodic recall on continuous beats.

Runs four large, sequential commerce-API tasks on one employee with a shortened beat budget so
work spills across multiple heartbeat ticks. Probes the event bus after every tick for:

- ``todo_write`` / ``read_file TODO.md`` (resume checklist)
- ``recall()`` / ``recall(query=…)`` (episodic orientation)
- timeout resumes vs completions

    uv run python examples/backend_engineer_cross_beat_probe.py

Requires AZURE_OPENAI_* in the repo-root ``.env``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

_EXAMPLE_COMPANY = str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-example"))  # one stable demo org
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from chorus.budgets import BudgetEnforcer
from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.memory import EpisodicStore, narrative
from chorus.observability import EventBus
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.roles._plugin import RolePlugin
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._env import load_env_file
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory

# Shorter than production 900s — forces timeout resume within a single large task.
_BEAT_TIMEOUT_S = float(os.environ.get("CHORUS_PROBE_BEAT_TIMEOUT_S", "180"))
_MAX_RESUME = int(os.environ.get("CHORUS_PROBE_MAX_RESUME", "8"))
_MAX_TICKS_PER_TASK = int(os.environ.get("CHORUS_PROBE_MAX_TICKS", "10"))

_MEGA_INTENT = (
    "Build the FULL commerce API (stdlib ONLY: http.server, sqlite3, json, secrets, hashlib). "
    "THREE domains auth/, orders/, payments/. GET /health. Auth register+login with salted hashes. "
    "Orders owner-only GET. Payments with Idempotency-Key. SQL migrations on startup. "
    "Prove restart durability. Full test sandwich + test_evidence pass."
)

# Four domain-sized slices of the commerce API — each too big for one short beat.
# Set CHORUS_PROBE_MODE=mega for one continuous task that should spill across many beats.
_DOMAIN_TASKS: tuple[tuple[str, str], ...] = (
    (
        "t1-auth",
        "Build the AUTH domain of a small commerce HTTP service (stdlib ONLY: http.server, sqlite3, "
        "json, secrets, hashlib — no pip). Start `python main.py` on PORT (default 8000). Organise as "
        "package `auth/` (domain → service → data-access → transport). Implement:\n"
        "  GET /health -> 200 'ok'\n"
        '  POST /auth/register {"email","password"} -> 201; store SALTED hash (hashlib), never '
        "plaintext; duplicate email -> 409\n"
        '  POST /auth/login {"email","password"} -> 200 {"token"} (opaque bearer via secrets); '
        "wrong creds -> 401\n"
        "Add unit tests for password hash+verify. Use todo_write for every step. Make tests pass.",
    ),
    (
        "t2-orders",
        "Extend the commerce service with an ORDERS domain (`orders/` package, dependencies inward). "
        "Protected routes require `Authorization: Bearer <token>` from auth (401 if missing). "
        "Implement:\n"
        '  POST /orders {"items":[{"sku","qty"}]} -> 201 {"order_id","total","status":"pending"} '
        "(fixed per-sku price table you define)\n"
        "  GET /orders/{id} -> 200 for OWNER only; another user's order -> 403 (object-level authz)\n"
        "Add integration tests for owner-only 403. Keep auth working. Reconcile TODO.md first beat. "
        "Make tests pass.",
    ),
    (
        "t3-payments",
        "Add PAYMENTS domain (`payments/` package). Auth required. Implement:\n"
        '  POST /payments {"order_id","amount"} -> 201 {"payment_id","status":"paid"} and flip '
        "order status to 'paid'\n"
        "  IDEMPOTENT on `Idempotency-Key` header — same key replays same payment, no double charge\n"
        "Unit test idempotency dedup; integration test pay-flips-order-status. Keep prior domains. "
        "Make tests pass.",
    ),
    (
        "t4-durability",
        "Add SQL MIGRATIONS on startup (ordered list in schema_migrations table, idempotent re-runs). "
        "DB_PATH env (default commerce.db). Prove data survives restart: integration test register -> "
        "login -> order -> pay -> order reads 'paid', STILL 'paid' after killing and restarting the "
        "server process. Run full test suite green. Land test_evidence manifest pass.",
    ),
)


def _tasks_for_run() -> tuple[tuple[str, str], ...]:
    if os.environ.get("CHORUS_PROBE_MODE") == "mega":
        return (("mega-commerce", _MEGA_INTENT),)
    return _DOMAIN_TASKS


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
    (path / "README.md").write_text("# commerce-api seed\n", encoding="utf-8")
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


def _registry_short_beats(timeout_s: float) -> RoleRegistry:
    plugins: list[RolePlugin] = []
    for plugin in default_roles():
        if plugin.name != "backend_engineer":
            plugins.append(plugin)
            continue
        manifest = replace(
            plugin.manifest,
            beat_timeout_s=timeout_s,
            lease_ttl_s=timeout_s + 90.0,
        )
        plugins.append(
            RolePlugin(
                name=plugin.name,
                manifest=manifest,
                dod_generator=plugin.dod_generator,
                outcome_kind=plugin.outcome_kind,
                declared_routines=plugin.declared_routines,
                replace=True,
            )
        )
    return RoleRegistry.from_plugins(plugins)


@dataclass
class _ToolStep:
    tool: str
    detail: str = ""
    is_error: bool = False


@dataclass
class _RecallCall:
    input: dict[str, object]
    is_error: bool
    preview: str = ""


@dataclass
class _BeatTrace:
    task_id: str
    tick: int
    run_id: str = ""
    started_at: float = 0.0
    tool_steps: list[_ToolStep] = field(default_factory=list)
    recall_calls: list[_RecallCall] = field(default_factory=list)
    outcome: str = "?"
    is_timeout: bool = False
    task_status: str = "?"
    todo_md_snapshot: str | None = None


class _ProbeBus(EventBus):
    def __init__(self) -> None:
        super().__init__(log_path=None)
        self.traces: list[_BeatTrace] = []
        self._current: _BeatTrace | None = None
        self._pending_recall: _RecallCall | None = None

    def start_beat(self, task_id: str, tick: int) -> None:
        self._current = _BeatTrace(task_id=task_id, tick=tick, started_at=time.monotonic())
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
                raw = p.get("input", {})
                inp = raw if isinstance(raw, dict) else {}
                detail = _tool_detail(tool, inp)
                self._current.tool_steps.append(_ToolStep(tool=tool, detail=detail))
                if tool == "recall":
                    self._pending_recall = _RecallCall(input=inp, is_error=False)
                    self._current.recall_calls.append(self._pending_recall)
            elif event.kind is EventKind.RUN_TOOL_RESULT and self._pending_recall is not None:
                if str(p.get("tool", "")) == "recall":
                    self._pending_recall.is_error = bool(p.get("is_error"))
                    content = p.get("content", p.get("output", ""))
                    self._pending_recall.preview = str(content)[:400]
                    self._pending_recall = None
            elif event.kind is EventKind.RUN_EVALUATED:
                self._current.outcome = str(p.get("outcome", "?"))
            elif event.kind is EventKind.RUN_DONE:
                err = str(p.get("error", p.get("outcome", {}).get("error", "")))
                if "TimeoutError" in err:
                    self._current.is_timeout = True
                    self._current.outcome = "TIMEOUT"
        except Exception:
            pass


def _tool_detail(tool: str, inp: dict[str, object]) -> str:
    if tool in ("read_file", "write_file"):
        return str(inp.get("path", ""))
    if tool == "todo_write":
        todos = inp.get("todos", [])
        if isinstance(todos, list):
            return f"{len(todos)} item(s)"
        return ""
    if tool == "run_command":
        return str(inp.get("command", ""))[:80]
    if tool == "recall":
        q = inp.get("query")
        return f"query={q!r}" if q else "(recency)"
    return ""


def _worktree_path(company_root: Path, employee_id: str) -> Path:
    return company_root / "worktrees" / employee_id


def _read_todo(worktree: Path) -> str | None:
    todo = worktree / "TODO.md"
    if not todo.is_file():
        return None
    return todo.read_text(encoding="utf-8")[:2000]


def _probe_tick(trace: _BeatTrace, worktree: Path) -> None:
    trace.todo_md_snapshot = _read_todo(worktree)
    tools = [s.tool for s in trace.tool_steps]
    todo_reads = sum(1 for s in trace.tool_steps if s.tool == "read_file" and "TODO.md" in s.detail)
    todo_writes = sum(1 for s in trace.tool_steps if s.tool == "todo_write")
    recalls = len(trace.recall_calls)
    elapsed = time.monotonic() - trace.started_at if trace.started_at else 0
    todo_preview = ""
    if trace.todo_md_snapshot:
        lines = [ln.strip() for ln in trace.todo_md_snapshot.splitlines() if ln.strip()][:3]
        todo_preview = " | ".join(lines)[:120]

    _log(
        f"  PROBE tick={trace.tick} outcome={trace.outcome} timeout={trace.is_timeout} "
        f"status={trace.task_status} tools={len(tools)} todo_r={todo_reads} todo_w={todo_writes} "
        f"recall={recalls} elapsed~{elapsed:.0f}s"
    )
    if todo_preview:
        _log(f"    TODO.md: {todo_preview}")
    if recalls:
        for rc in trace.recall_calls:
            mode = f"query={rc.input.get('query')!r}" if rc.input.get("query") else "recency"
            hit = "hit" if rc.preview and "no past beats" not in rc.preview else "empty"
            _log(f"    recall({mode}) → {'ERR' if rc.is_error else hit}")
    # Early-tool ordering signal for resume beats
    if trace.tick > 1 or trace.is_timeout:
        head = tools[:6]
        _log(f"    tool order (first 6): {' → '.join(head) or '(none)'}")


async def _run_task(
    scheduler: Scheduler,
    ledger: Ledger,
    bus: _ProbeBus,
    worktree: Path,
    task_id: str,
) -> list[_BeatTrace]:
    traces: list[_BeatTrace] = []
    for tick in range(1, _MAX_TICKS_PER_TASK + 1):
        task = ledger.tasks.get(task_id)
        if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
            break
        _log(f"\n  ▷ tick {tick}/{_MAX_TICKS_PER_TASK} …")
        bus.start_beat(task_id, tick)
        await scheduler.tick_once()
        await scheduler.drain()
        trace = bus.traces[-1]
        task_now = ledger.tasks.get(task_id)
        trace.task_status = task_now.status.value if task_now else "?"
        # mark timeout from ledger if bus missed RUN_DONE error shape
        runs = ledger.runs.for_task(task_id)
        if runs:
            latest = runs[-1]
            if "TimeoutError" in str(latest.outcome):
                trace.is_timeout = True
                if trace.outcome in ("?", ""):
                    trace.outcome = "TIMEOUT"
        _probe_tick(trace, worktree)
        traces.append(trace)
        if task.status is TaskStatus.DONE:
            break
    return traces


def _score(
    all_traces: list[_BeatTrace],
    store: EpisodicStore,
    employee_id: str,
    completed: int,
    *,
    total_tasks: int,
) -> list[tuple[str, bool, str]]:
    records = store.records_for(employee_id)
    timeouts = [t for t in all_traces if t.is_timeout]
    resume_ticks = [t for t in all_traces if t.tick > 1]
    later_tasks = [t for t in all_traces if not t.task_id.startswith("t1")]

    todo_exists_any = any(t.todo_md_snapshot for t in all_traces)
    todo_read_resume = sum(
        1
        for t in resume_ticks
        if any(s.tool == "read_file" and "TODO.md" in s.detail for s in t.tool_steps)
    )
    todo_write_any = sum(1 for t in all_traces if any(s.tool == "todo_write" for s in t.tool_steps))
    recall_total = sum(len(t.recall_calls) for t in all_traces)
    recall_resume = sum(1 for t in resume_ticks if t.recall_calls)
    recall_later_tasks = sum(1 for t in later_tasks if t.recall_calls)
    recall_errors = sum(1 for t in all_traces for c in t.recall_calls if c.is_error)
    query_recalls = sum(
        1 for t in all_traces for c in t.recall_calls if c.input.get("query") and not c.is_error
    )

    # Advantage: on resume ticks, did agent orient before coding?
    oriented_resume = 0
    for t in resume_ticks:
        early = t.tool_steps[:5]
        has_todo = any(s.tool == "read_file" and "TODO.md" in s.detail for s in early)
        has_recall = any(s.tool == "recall" for s in early)
        if has_todo or has_recall:
            oriented_resume += 1

    checks: list[tuple[str, bool, str]] = [
        (
            "multiple beats observed (timeouts or multi-tick tasks)",
            len(all_traces) >= 5 or len(timeouts) >= 1,
            f"{len(all_traces)} beat trace(s), {len(timeouts)} timeout(s)",
        ),
        (
            "TODO.md materializes in worktree",
            todo_exists_any,
            "present" if todo_exists_any else "missing",
        ),
        (
            "todo_write used at least once",
            todo_write_any >= 1,
            f"{todo_write_any} beat(s) called todo_write",
        ),
        (
            "resume ticks read TODO.md (brief protocol)",
            todo_read_resume >= 1 or len(resume_ticks) == 0,
            f"{todo_read_resume}/{len(resume_ticks)} resume tick(s) read TODO.md",
        ),
        (
            "episodic records accumulate",
            len(records) >= 2,
            f"{len(records)} record(s)",
        ),
        (
            "recall invoked across run",
            recall_total >= 1,
            f"{recall_total} call(s)",
        ),
        (
            "recall on resume or later tasks",
            recall_resume >= 1 or recall_later_tasks >= 1,
            f"resume={recall_resume}, later_tasks={recall_later_tasks}",
        ),
        (
            "recall calls succeed",
            recall_errors == 0,
            f"{recall_errors} error(s)",
        ),
        (
            "search recall (query=) or multiple recency calls",
            query_recalls >= 1 or recall_total >= 2,
            f"{query_recalls} query call(s), {recall_total} total",
        ),
        (
            "resume beats orient via TODO and/or recall early",
            oriented_resume >= max(1, len(resume_ticks) // 2) if resume_ticks else True,
            f"{oriented_resume}/{len(resume_ticks)} resume tick(s) oriented in first 5 tools",
        ),
        (
            f"at least {1 if total_tasks == 1 else 2} task(s) complete",
            completed >= (1 if total_tasks == 1 else 2),
            f"{completed}/{total_tasks} done",
        ),
    ]
    # Recall payload quality: no operational garbage in previews
    trash = ("docs/exec-plans", "commerce.db", ".harness/")
    dirty = [
        c.preview
        for t in all_traces
        for c in t.recall_calls
        if any(tok in c.preview for tok in trash)
    ]
    checks.append(
        (
            "recall previews exclude operational noise paths",
            len(dirty) == 0,
            f"{len(dirty)} dirty recall preview(s)",
        )
    )
    return checks


def main() -> int:
    load_env_file(Path(__file__).resolve().parent.parent / ".env", override=True)
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        _log("skipping: set AZURE_OPENAI_* in .env")
        return 0

    base = Path(tempfile.mkdtemp(prefix="chorus-cross-beat-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = Ledger.open(
        os.environ.get("CHORUS_LEDGER_DSN", "postgresql://localhost/chorus"),
        company_id=_EXAMPLE_COMPANY,
    )
    bus = _ProbeBus()
    _reports = Path(__file__).resolve().parent.parent / "reports"
    _probe_slug = (
        "backend-engineer-cross-beat-probe-mega.json"
        if os.environ.get("CHORUS_PROBE_MODE") == "mega"
        else "backend-engineer-cross-beat-probe-domain.json"
    )
    report_path = _reports / _probe_slug
    log_path = report_path.with_suffix(".log")

    try:
        registry = _registry_short_beats(_BEAT_TIMEOUT_S)
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
        worktree = _worktree_path(factory.company_root, "bex")

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
            max_resume_attempts=_MAX_RESUME,
        )

        _log("=" * 72)
        _log("BACKEND ENGINEER CROSS-BEAT PROBE")
        _log(f"  beat_timeout   : {_BEAT_TIMEOUT_S}s")
        _log(f"  max_resume     : {_MAX_RESUME}")
        _log(f"  max_ticks/task : {_MAX_TICKS_PER_TASK}")
        _log(f"  company_root   : {factory.company_root}")
        _log(f"  worktree       : {worktree}")
        _log(f"  deployment     : {deployment}")
        _log("=" * 72)

        completed = 0
        all_task_traces: list[_BeatTrace] = []

        tasks = _tasks_for_run()
        for task_id, intent in tasks:
            _log(f"\n{'=' * 72}")
            _log(f"TASK {task_id}")
            _log(f"  {intent[:140]}…")
            ledger.tasks.submit(Task(id=task_id, intent=intent))
            assign_task(ledger, task_id, "bex")
            ledger.dod.create(task_id, _DOD)

            traces = asyncio.run(_run_task(scheduler, ledger, bus, worktree, task_id))
            all_task_traces.extend(traces)
            final = ledger.tasks.get(task_id)
            status = final.status.value if final else "?"
            _log(f"  → final status: {status}")
            if final and final.status is TaskStatus.DONE:
                completed += 1

        checks = _score(all_task_traces, store, "bex", completed, total_tasks=len(tasks))
        records = store.records_for("bex")

        _log(f"\n{'=' * 72}")
        _log("EPISODIC STORE")
        for r in records:
            _log(f"  {r.run_id[:12]}… outcome={r.outcome} files={list(r.files_touched)[:4]}")

        _log("\nHARNESS CHECKS")
        all_ok = True
        for name, ok, detail in checks:
            _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
            all_ok = all_ok and ok

        payload = {
            "probe_mode": os.environ.get("CHORUS_PROBE_MODE", "domain"),
            "beat_timeout_s": _BEAT_TIMEOUT_S,
            "max_resume": _MAX_RESUME,
            "completed_tasks": completed,
            "total_tasks": len(tasks),
            "episodic_records": len(records),
            "timeout_beats": sum(1 for t in all_task_traces if t.is_timeout),
            "stored_records": [
                {
                    "run_id": r.run_id,
                    "outcome": r.outcome,
                    "intent": r.intent[:200],
                    "files_touched": list(r.files_touched),
                    "prose_snippet": narrative(r.body)[:300],
                }
                for r in records
            ],
            "traces": [
                {
                    "task_id": t.task_id,
                    "tick": t.tick,
                    "run_id": t.run_id,
                    "outcome": t.outcome,
                    "is_timeout": t.is_timeout,
                    "task_status": t.task_status,
                    "todo_md_lines": (
                        len(t.todo_md_snapshot.splitlines()) if t.todo_md_snapshot else 0
                    ),
                    "todo_md_preview": (
                        "\n".join(t.todo_md_snapshot.splitlines()[:12])
                        if t.todo_md_snapshot
                        else ""
                    ),
                    "recall_calls": [
                        {"input": c.input, "is_error": c.is_error, "preview": c.preview}
                        for c in t.recall_calls
                    ],
                    "tools": [{"tool": s.tool, "detail": s.detail} for s in t.tool_steps],
                }
                for t in all_task_traces
            ],
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        alias = _reports / "backend-engineer-cross-beat-probe.json"
        alias.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log_path.write_text("\n".join(_log_lines_from_payload(payload)), encoding="utf-8")
        _log(f"\nreport: {report_path}")
        _log(f"alias : {alias}")
        _log(f"log   : {log_path}")
        _log(
            f"\n{'ALL CHECKS PASS' if all_ok else 'SOME CHECKS FAILED'} "
            f"({completed}/{len(tasks)} tasks, {len(all_task_traces)} beats, "
            f"{payload['timeout_beats']} timeouts)"
        )
        return 1 if not all_ok else 0
    finally:
        ledger.close()


def _log_lines_from_payload(payload: dict[str, object]) -> str:
    lines = [
        f"completed={payload.get('completed_tasks')}/{payload.get('total_tasks')}",
        f"timeouts={payload.get('timeout_beats')}",
    ]
    for t in payload.get("traces", []):
        if not isinstance(t, dict):
            continue
        lines.append(
            f"{t.get('task_id')} tick={t.get('tick')} {t.get('outcome')} "
            f"recall={len(t.get('recall_calls', []))} tools={len(t.get('tools', []))}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
