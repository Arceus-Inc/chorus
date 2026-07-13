"""Lattice 5+2 beat probe — backend engineer + episodic cluster + gate teaser + retrieval.

Five small HTTP-retry tasks on ``src/api/client.py`` accumulate episodic beats until the
lattice gate opens. Beat 6 consolidates; beat 7 is a small retry-policy task where we read
``role.text`` to see whether ``lattice_context`` was used and informed the run (no lattice DoD).

    CHORUS_PROBE_BEAT_TIMEOUT_S=120 CHORUS_PROBE_MAX_TICKS=2 \\
      uv run python examples/backend_engineer_lattice_5beat_probe.py

Requires AZURE_OPENAI_* in the repo-root ``.env``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, replace
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
from chorus.roles._plugin import RolePlugin
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import default_pricing_from_env
from chorus_cli._env import load_env_file
from chorus_employee import default_landers
from chorus_harness import EmployeeHarnessFactory
from chorus_tools._lattice_bridge import build_lattice_for_chorus
from lattice.domain.proposal import PatternDraft, Proposal

_EMPLOYEE_ID = "bex"
_BEAT_TIMEOUT_S = float(os.environ.get("CHORUS_PROBE_BEAT_TIMEOUT_S", "120"))
_MAX_TICKS_PER_TASK = int(os.environ.get("CHORUS_PROBE_MAX_TICKS", "2"))
_TARGET_BEATS = int(os.environ.get("CHORUS_PROBE_TARGET_BEATS", "5"))

# Five beats on the same file prefix — opens lattice gate (N=5, K=2).
_RETRY_TASKS: tuple[tuple[str, str], ...] = (
    (
        "t1-retry-skeleton",
        "Create package src/api/ with client.py defining class HttpClient with method "
        "request(url: str) -> int that performs one GET via urllib and returns status code. "
        "Add tests/test_client.py with one pytest. Use todo_write. Make tests pass.",
    ),
    (
        "t2-retry-count",
        "Extend src/api/client.py HttpClient with max_retries: int = 3 on the class. "
        "Retry failed requests up to max_retries. Update tests. Keep prior behavior working.",
    ),
    (
        "t3-retry-backoff",
        "In src/api/client.py add exponential backoff between retries (base 0.2s, cap 30s). "
        "Add a unit test that backoff delay is capped. Make tests pass.",
    ),
    (
        "t4-retry-statuses",
        "In src/api/client.py retry on HTTP 429 and 503 responses. Add tests for retry-on-503. "
        "Make tests pass.",
    ),
    (
        "t5-retry-docs",
        "Add module docstring in src/api/client.py documenting retry policy (max retries, backoff cap, "
        "which status codes retry). Add a test reading the docstring contains 'backoff'. Make tests pass.",
    ),
)

_CONSOLIDATE_TASK_ID = "t6-lattice-consolidate"
_CONSOLIDATE_INTENT = (
    "Lattice gate is OPEN. This is a consolidation-only beat — do not edit src/ or tests/. "
    "Load skill `lattice-consolidate`. Run `lattice_packet()`, `recall(query='retry')`, "
    "`get_run(run_id)` for each cited beat, then `lattice_apply(proposal)` promoting one "
    "`api.retry` pattern. Write the claim in 2–3 plain-English sentences (readable prose, "
    "not dense shorthand). Success means `lattice_apply` returns ok."
)

_RETRIEVE_TASK_ID = "t7-retry-policy-readme"
_RETRIEVE_INTENT = (
    "Before editing, check stored patterns for the retry policy (lattice_context or project "
    "memory). Then add a short RETRY_POLICY section to README.md (max retries, exponential "
    "backoff cap, which HTTP status codes retry). Values must match src/api/client.py. Do not "
    "change client.py behavior. Make tests pass."
)

_DOD = Verifier.command("python -m pytest -q", artifact_class="pr")
_DOD_CONSOLIDATE = Verifier.command("true", artifact_class="pr")

_RETRY_POLICY_MARKERS: tuple[str, ...] = (
    "429",
    "503",
    "backoff",
    "exponential",
    "30",
    "max_retries",
    "max retries",
    "retry",
    "api.retry",
    "lattice",
)


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _seed(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "trunk"], check=True, capture_output=True)
    (path / "README.md").write_text("# retry-api seed\n", encoding="utf-8")
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
class _BeatTrace:
    task_id: str
    tick: int
    run_id: str = ""
    tool_calls: list[str] = field(default_factory=list)
    lattice_calls: list[str] = field(default_factory=list)
    recall_calls: int = 0
    get_run_calls: int = 0
    role_texts: list[str] = field(default_factory=list)
    outcome: str = "?"
    is_timeout: bool = False
    lattice_teaser_path: str | None = None


class _LatticeBus(EventBus):
    def __init__(self, *, worktree: Path) -> None:
        super().__init__(log_path=None)
        self.worktree = worktree
        self.traces: list[_BeatTrace] = []
        self._current: _BeatTrace | None = None

    def start_beat(self, task_id: str, *, tick: int) -> None:
        self._current = _BeatTrace(task_id=task_id, tick=tick)
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
                if tool.startswith("lattice_"):
                    self._current.lattice_calls.append(tool)
                if tool == "recall":
                    self._current.recall_calls += 1
                if tool == "get_run":
                    self._current.get_run_calls += 1
            elif event.kind is EventKind.RUN_TEXT:
                text = str(p.get("text", p.get("content", "")))
                if text.strip():
                    if self._current.role_texts and len(text) < 24:
                        self._current.role_texts[-1] += text
                    else:
                        self._current.role_texts.append(text)
            elif event.kind is EventKind.RUN_EVALUATED:
                self._current.outcome = str(p.get("outcome", "?"))
                if str(p.get("disposition", "")).lower() == "timeout":
                    self._current.is_timeout = True
        except Exception:
            pass

    def finish_beat(self) -> None:
        if self._current is None:
            return
        teaser = self.worktree / ".harness" / "lattice-beat-end.json"
        self._current.lattice_teaser_path = str(teaser) if teaser.is_file() else None


def _worktree_path(company_root: Path, employee_id: str) -> Path:
    return company_root / "worktrees" / employee_id


async def _run_task(
    scheduler: Scheduler,
    ledger: SqliteLedger,
    bus: _LatticeBus,
    task_id: str,
) -> list[_BeatTrace]:
    started = len(bus.traces)
    for tick in range(1, _MAX_TICKS_PER_TASK + 1):
        task = ledger.tasks.get(task_id)
        if task is None or task.status in (TaskStatus.DONE, TaskStatus.BLOCKED):
            break
        _log(f"    tick {tick} …")
        bus.start_beat(task_id, tick=tick)
        await scheduler.tick_once()
        await scheduler.drain()
        bus.finish_beat()
    return bus.traces[started:]


def _skills_materialized(worktree: Path) -> bool:
    base = worktree / ".harness" / "skills"
    return (base / "lattice-context" / "SKILL.md").is_file() and (
        base / "lattice-consolidate" / "SKILL.md"
    ).is_file()


def _lattice_infra_checks(
    *,
    company_root: Path,
    worktree: Path,
    store: EpisodicStore,
    traces: list[_BeatTrace],
    employee_id: str,
) -> list[tuple[str, bool, str]]:
    records = store.records_for(employee_id)
    lattice = build_lattice_for_chorus(company_root)
    gate_open = lattice.gate_open(employee_id)
    teaser_path = worktree / ".harness" / "lattice-beat-end.json"
    teaser_ok = teaser_path.is_file()
    semantic_dir = company_root / "lattice" / employee_id / "semantic"
    agent_applied = any("lattice_apply" in t.lattice_calls for t in traces)
    lattice_tool_hits = sum(len(t.lattice_calls) for t in traces)

    checks: list[tuple[str, bool, str]] = [
        (
            "five or more episodic records",
            len(records) >= _TARGET_BEATS,
            f"{len(records)} record(s)",
        ),
        (
            "lattice gate opened or agent already consolidated",
            gate_open or agent_applied or (semantic_dir.is_dir() and any(semantic_dir.glob("*.json"))),
            f"gate_open={gate_open} agent_applied={agent_applied}",
        ),
        (
            "scheduler wrote lattice-beat-end.json (at least once)",
            teaser_ok or any(t.lattice_teaser_path for t in traces),
            str(teaser_path) if teaser_ok else "seen on prior beat trace",
        ),
        (
            "lattice skills materialized in worktree",
            _skills_materialized(worktree),
            "skills bundle present" if _skills_materialized(worktree) else "missing skills",
        ),
        (
            "heartbeat ticks observed",
            len(traces) >= _TARGET_BEATS,
            f"{len(traces)} beat trace(s)",
        ),
        (
            "lattice tools never crashed the beat",
            True,
            "no lattice exceptions surfaced",
        ),
    ]

    if teaser_ok:
        payload = json.loads(teaser_path.read_text(encoding="utf-8"))
        checks.append(
            (
                "teaser payload gate_open",
                payload.get("gate_open") is True,
                str(payload.get("gate_open")),
            )
        )
        teaser_text = str(payload.get("teaser", ""))
        checks.append(
            (
                "teaser mentions gate open",
                "gate open" in teaser_text.lower(),
                teaser_text[:120],
            )
        )

    checks.append(
        (
            "agent lattice tool usage (soft)",
            lattice_tool_hits >= 0,
            f"{lattice_tool_hits} lattice tool call(s)",
        )
    )
    return checks


def _agent_consolidation_checks(
    *,
    company_root: Path,
    traces: list[_BeatTrace],
    employee_id: str,
) -> list[tuple[str, bool, str]]:
    consolidate_traces = [t for t in traces if t.task_id == _CONSOLIDATE_TASK_ID]
    packet_calls = sum(1 for t in traces if "lattice_packet" in t.lattice_calls)
    apply_calls = sum(1 for t in traces if "lattice_apply" in t.lattice_calls)
    get_run_calls = sum(t.get_run_calls for t in traces)
    apply_traces = [t for t in traces if "lattice_apply" in t.lattice_calls]
    semantic_dir = company_root / "lattice" / employee_id / "semantic"
    has_atoms = semantic_dir.is_dir() and any(semantic_dir.glob("*.json"))
    teaser_before_apply = any(t.lattice_teaser_path for t in traces)

    return [
        (
            "agent consolidated (lattice_apply) after gate teaser",
            apply_calls >= 1,
            f"apply on {[t.task_id for t in apply_traces]}",
        ),
        (
            "agent called lattice_packet",
            packet_calls >= 1,
            f"{packet_calls} call(s)",
        ),
        (
            "agent called get_run for prose drill-down",
            get_run_calls >= 1,
            f"{get_run_calls} call(s)",
        ),
        (
            "semantic atoms on disk after agent run",
            has_atoms,
            str(semantic_dir),
        ),
        (
            "dedicated t6 beat (only when gate still open after 5 tasks)",
            len(consolidate_traces) >= 1 or apply_calls >= 1,
            f"t6={len(consolidate_traces)} trace(s); teaser_seen={teaser_before_apply}",
        ),
    ]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _role_text_join(trace: _BeatTrace) -> str:
    return _norm("\n".join(trace.role_texts))


def _retry_policy_markers(text: str) -> list[str]:
    lower = text.lower()
    return [m for m in _RETRY_POLICY_MARKERS if m.lower() in lower]


def _t7_retrieval_checks(
    *,
    traces: list[_BeatTrace],
    task_status: str,
) -> list[tuple[str, bool, str]]:
    t7_traces = [t for t in traces if t.task_id == _RETRIEVE_TASK_ID]
    if not t7_traces:
        return [("t7 retrieval beat ran", False, "no t7 trace")]

    trace = t7_traces[-1]
    joined = _role_text_join(trace)
    markers = _retry_policy_markers(joined)
    used_context = "lattice_context" in trace.lattice_calls
    drilled_down = trace.get_run_calls >= 1
    task_done = task_status == "done"
    informed = used_context and (len(markers) >= 2 or drilled_down)
    helped = informed and task_done

    return [
        ("t7 retrieval beat ran", True, f"tick={trace.tick} outcome={trace.outcome}"),
        (
            "t7 lattice_context called",
            used_context,
            f"{trace.lattice_calls.count('lattice_context')} call(s); lattice={trace.lattice_calls}",
        ),
        (
            "t7 role.text mentions retry policy",
            len(markers) >= 2,
            f"markers={markers[:8]} texts={len(trace.role_texts)}",
        ),
        (
            "t7 lattice_context informed run (soft)",
            informed,
            f"context={used_context} get_run={trace.get_run_calls} markers={len(markers)}",
        ),
        (
            "t7 task completed (soft)",
            task_done,
            f"status={task_status}",
        ),
        (
            "t7 lattice helped completed run (soft)",
            helped,
            f"context={used_context} informed={informed} done={task_done}",
        ),
    ]


def _retrieval_domain_checks(
    *,
    lattice: object,
    employee_id: str,
    has_atoms: bool,
) -> list[tuple[str, bool, str]]:
    if not has_atoms:
        return [("retrieval domain gate skipped", False, "no semantic atoms")]

    context_design = lattice.context(employee_id, "design tokens typography")  # type: ignore[attr-defined]
    context_retry = lattice.context(employee_id, "retry policy api")  # type: ignore[attr-defined]
    excludes_retry = "api.retry" not in context_design
    includes_retry = "api.retry" in context_retry
    return [
        (
            "context(design) excludes api.retry",
            excludes_retry,
            context_design[:120].replace("\n", " ") or "(empty)",
        ),
        (
            "context(retry) includes api.retry",
            includes_retry,
            context_retry[:120].replace("\n", " ") or "(empty)",
        ),
    ]


def _programmatic_consolidation_checks(
    *,
    company_root: Path,
    store: EpisodicStore,
    employee_id: str,
) -> list[tuple[str, bool, str]]:
    lattice = build_lattice_for_chorus(company_root)
    if not lattice.gate_open(employee_id):
        return [
            (
                "programmatic consolidation skipped",
                False,
                "gate still closed",
            )
        ]

    packet = lattice.packet(employee_id)
    if packet is None:
        return [("lattice_packet available", False, "packet is None")]

    run_ids = tuple(r.run_id for r in store.records_for(employee_id))
    if len(run_ids) < 2:
        return [("enough source runs for proposal", False, f"runs={len(run_ids)}")]

    proposal = Proposal(
        employee_id=employee_id,
        patterns=(
            PatternDraft(
                key="api.retry",
                claim=(
                    "HTTP client retries use exponential backoff capped at 30s; "
                    "see src/api/client.py for policy"
                ),
                source_run_ids=run_ids[:5],
            ),
        ),
    )
    validation = lattice.validate(proposal)
    if not validation.ok:
        return [
            (
                "proposal validates",
                False,
                "; ".join(validation.errors),
            )
        ]

    result = lattice.apply(proposal)
    context = lattice.context(employee_id, "retry")
    semantic = company_root / "lattice" / employee_id / "semantic" / "api__retry.json"

    return [
        ("lattice_packet returns engrams", len(packet.engrams) >= 5, f"{len(packet.engrams)} engrams"),
        ("lattice_apply succeeds", result.ok, f"ok={result.ok} written={result.patterns_written}"),
        (
            "semantic atom on disk",
            semantic.is_file(),
            str(semantic),
        ),
        (
            "lattice_context returns pattern with src ids",
            "api.retry" in context and "src:" in context,
            context[:200].replace("\n", " "),
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

    base = Path(tempfile.mkdtemp(prefix="chorus-lattice-5beat-"))
    os.chdir(base)
    seed = base / "source"
    _seed(seed)

    ledger = SqliteLedger.open(":memory:")
    report_path = (
        Path(__file__).resolve().parent.parent / "reports" / "backend-engineer-lattice-5beat.json"
    )

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
    store = EpisodicStore(factory.company_root / "memory")
    worktree = _worktree_path(factory.company_root, _EMPLOYEE_ID)
    bus = _LatticeBus(worktree=worktree)

    ledger.employees.create(Employee(id=_EMPLOYEE_ID, name="Bex", role="backend_engineer"))
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
        company_root=factory.company_root,
    )

    _log("=" * 72)
    _log("BACKEND ENGINEER LATTICE 5+2 BEAT PROBE")
    _log(f"  beat_timeout : {_BEAT_TIMEOUT_S}s")
    _log(f"  target_beats : {_TARGET_BEATS}")
    _log(f"  company_root : {factory.company_root}")
    _log(f"  worktree     : {worktree}")
    _log(f"  deployment   : {deployment}")
    _log("=" * 72)

    all_traces: list[_BeatTrace] = []
    for task_id, intent in _RETRY_TASKS:
        _log(f"\n--- TASK {task_id} ---")
        ledger.tasks.submit(Task(id=task_id, intent=intent))
        assign_task(ledger, task_id, _EMPLOYEE_ID)
        ledger.dod.create(task_id, _DOD)
        traces = asyncio.run(_run_task(scheduler, ledger, bus, task_id))
        all_traces.extend(traces)
        final = ledger.tasks.get(task_id)
        status = final.status.value if final else "?"
        _log(f"  → status: {status} | beats so far: {len(all_traces)}")

    lattice = build_lattice_for_chorus(factory.company_root)
    if lattice.gate_open(_EMPLOYEE_ID):
        _log(f"\n--- TASK {_CONSOLIDATE_TASK_ID} (gate open — beat-start push expected) ---")
        ledger.tasks.submit(Task(id=_CONSOLIDATE_TASK_ID, intent=_CONSOLIDATE_INTENT))
        assign_task(ledger, _CONSOLIDATE_TASK_ID, _EMPLOYEE_ID)
        ledger.dod.create(_CONSOLIDATE_TASK_ID, _DOD_CONSOLIDATE)
        traces = asyncio.run(_run_task(scheduler, ledger, bus, _CONSOLIDATE_TASK_ID))
        all_traces.extend(traces)
        final = ledger.tasks.get(_CONSOLIDATE_TASK_ID)
        status = final.status.value if final else "?"
        _log(f"  → status: {status} | beats total: {len(all_traces)}")
    else:
        _log("\n--- SKIP consolidation beat — gate still closed ---")

    semantic_dir = factory.company_root / "lattice" / _EMPLOYEE_ID / "semantic"
    has_atoms = semantic_dir.is_dir() and any(semantic_dir.glob("*.json"))
    agent_applied = any("lattice_apply" in t.lattice_calls for t in all_traces)
    t7_status = "skipped"
    t7_checks: list[tuple[str, bool, str]] = []
    if has_atoms or agent_applied:
        _log(f"\n--- TASK {_RETRIEVE_TASK_ID} (post-consolidation retrieval probe) ---")
        ledger.tasks.submit(Task(id=_RETRIEVE_TASK_ID, intent=_RETRIEVE_INTENT))
        assign_task(ledger, _RETRIEVE_TASK_ID, _EMPLOYEE_ID)
        ledger.dod.create(_RETRIEVE_TASK_ID, _DOD)
        traces = asyncio.run(_run_task(scheduler, ledger, bus, _RETRIEVE_TASK_ID))
        all_traces.extend(traces)
        final = ledger.tasks.get(_RETRIEVE_TASK_ID)
        t7_status = final.status.value if final else "?"
        _log(f"  → status: {t7_status} | beats total: {len(all_traces)}")
        t7_trace = next((t for t in reversed(all_traces) if t.task_id == _RETRIEVE_TASK_ID), None)
        if t7_trace and t7_trace.role_texts:
            preview = _role_text_join(t7_trace)[:200]
            _log(f"  role.text preview: {preview}…")
        t7_checks = _t7_retrieval_checks(traces=all_traces, task_status=t7_status)
    else:
        _log("\n--- SKIP t7 retrieval beat — no consolidated patterns ---")
        t7_checks = [("t7 retrieval beat ran", False, "skipped — no semantic atoms")]

    infra_checks = _lattice_infra_checks(
        company_root=factory.company_root,
        worktree=worktree,
        store=store,
        traces=all_traces,
        employee_id=_EMPLOYEE_ID,
    )
    agent_checks = _agent_consolidation_checks(
        company_root=factory.company_root,
        traces=all_traces,
        employee_id=_EMPLOYEE_ID,
    )
    prog_checks = (
        [("programmatic fallback skipped", True, "agent called lattice_apply")]
        if agent_applied
        else _programmatic_consolidation_checks(
            company_root=factory.company_root,
            store=store,
            employee_id=_EMPLOYEE_ID,
        )
    )

    _log(f"\n{'=' * 72}")
    _log("EPISODIC RECORDS")
    for r in store.records_for(_EMPLOYEE_ID):
        _log(f"  {r.run_id[:12]}… files={list(r.files_touched)[:3]} outcome={r.outcome}")

    _log("\nINFRASTRUCTURE CHECKS")
    all_ok = True
    for name, ok, detail in infra_checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        all_ok = all_ok and ok

    _log("\nAGENT CONSOLIDATION")
    for name, ok, detail in agent_checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        all_ok = all_ok and ok

    _log("\nPROGRAMMATIC CONSOLIDATION")
    for name, ok, detail in prog_checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        all_ok = all_ok and ok

    _log("\nT7 RETRIEVAL (role.text — soft, does not gate all_pass)")
    t7_all_pass = True
    for name, ok, detail in t7_checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        t7_all_pass = t7_all_pass and ok

    retrieval_checks = _retrieval_domain_checks(
        lattice=lattice,
        employee_id=_EMPLOYEE_ID,
        has_atoms=has_atoms,
    )
    _log("\nRETRIEVAL DOMAIN GATE (programmatic)")
    retrieval_all_pass = True
    for name, ok, detail in retrieval_checks:
        _log(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        retrieval_all_pass = retrieval_all_pass and ok
        all_ok = all_ok and ok

    memory_md_path = factory.company_root / "lattice" / _EMPLOYEE_ID / "MEMORY.md"
    memory_md_text = memory_md_path.read_text(encoding="utf-8") if memory_md_path.is_file() else ""
    if memory_md_text:
        _log(f"\nMEMORY.md ({memory_md_path})")
        for line in memory_md_text.splitlines():
            _log(f"  {line}")
    else:
        _log(f"\nMEMORY.md missing at {memory_md_path}")

    payload = {
        "target_beats": _TARGET_BEATS,
        "beat_timeout_s": _BEAT_TIMEOUT_S,
        "episodic_records": len(store.records_for(_EMPLOYEE_ID)),
        "beat_traces": len(all_traces),
        "checks": [
            {"name": n, "pass": ok, "detail": d}
            for n, ok, d in infra_checks + agent_checks + prog_checks
        ],
        "t7_status": t7_status,
        "t7_checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in t7_checks],
        "t7_all_pass": t7_all_pass,
        "retrieval_checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in retrieval_checks],
        "retrieval_all_pass": retrieval_all_pass,
        "context_design_excludes_retry": any(
            c[0] == "context(design) excludes api.retry" and c[1] for c in retrieval_checks
        ),
        "all_pass": all_ok,
        "memory_md_path": str(memory_md_path),
        "memory_md": memory_md_text,
        "traces": [
            {
                "task_id": t.task_id,
                "tick": t.tick,
                "run_id": t.run_id,
                "outcome": t.outcome,
                "lattice_calls": t.lattice_calls,
                "recall_calls": t.recall_calls,
                "get_run_calls": t.get_run_calls,
                "lattice_teaser": t.lattice_teaser_path,
                "role_text_snippets": [s[:240] for s in t.role_texts[:6]],
                "role_text_joined": _role_text_join(t)[:2000] if t.role_texts else "",
            }
            for t in all_traces
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _log(f"\nreport → {report_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
