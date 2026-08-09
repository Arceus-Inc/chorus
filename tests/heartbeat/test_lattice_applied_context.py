"""Exact Lattice context hits land once with the scheduler's authoritative outcome phase."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn, cast

import psycopg
import pytest
from dream.tools._context import ToolExecutionContext
from dream.tools._registry import ToolRegistry
from lattice.contracts.applied import (
    AppliedAtomEdge,
    AppliedEdgeConflictError,
    LandedOutcomePhase,
)
from lattice.contracts.atom import Atom, ContextAtomHit
from lattice.contracts.episodic import RawEpisode
from lattice.contracts.selection import ContextAtomSelection, ContextSelectionConflictError
from lattice.domain.result import ContextResult, ContextSelectionCaptureResult
from lattice.facade import Lattice
from lattice.migrations import load_migrations
from lattice.stores.postgres import PostgresLatticeStore

from chorus.events import Event, EventKind
from chorus.heartbeat import BeatContext, Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.lattice import LatticeRuntime
from chorus.ledger import Ledger, RunStatus, Task, TaskStatus
from chorus.observability import EventSink
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce
from chorus_harness import _factory as harness_factory_module
from chorus_tools._lattice import LatticeContextTool

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 8, 9, tzinfo=UTC)


@dataclass(frozen=True)
class _LandedSelectionCall:
    employee_id: str
    beat_run_id: str
    outcome_phase: LandedOutcomePhase
    landed_at: datetime
    selections: tuple[ContextAtomSelection, ...]


class _RecordingLattice:
    def __init__(self, contexts: dict[tuple[str, str], ContextResult] | None = None) -> None:
        self._contexts = contexts or {}
        self._selections: dict[tuple[str, str], tuple[ContextAtomSelection, ...]] = {}
        self.capture_calls: list[tuple[str, str]] = []
        self.landed_calls: list[_LandedSelectionCall] = []
        self.recorded_edges: list[AppliedAtomEdge] = []
        self.call_order: list[str] = []
        self.fail_capture = False
        self.fail_recording = False
        self.recording_conflict: Exception | None = None
        self.durable_capture = True
        self.context_calls = 0

    def context_result(self, employee_id: str, query: str, *, k: int = 5) -> ContextResult:
        del k
        self.context_calls += 1
        return self._contexts[(employee_id, query)]

    def capture_context_selection(
        self,
        employee_id: str,
        context: ContextResult,
        *,
        beat_run_id: str,
    ) -> ContextSelectionCaptureResult:
        self.call_order.append("capture")
        self.capture_calls.append((employee_id, beat_run_id))
        if self.fail_capture:
            raise RuntimeError("postgres selection journal unavailable")
        skipped = tuple(hit for hit in context.hits if hit.revision is None)
        selected = tuple(
            ContextAtomSelection(
                employee_id=employee_id,
                beat_run_id=beat_run_id,
                key=hit.key,
                revision=hit.revision,
            )
            for hit in context.hits
            if hit.revision is not None
        )
        prior = self._selections.get((employee_id, beat_run_id), ())
        prior_keys = {selection.key for selection in prior}
        selected = (
            *prior,
            *(selection for selection in selected if selection.key not in prior_keys),
        )
        self._selections[(employee_id, beat_run_id)] = selected
        return ContextSelectionCaptureResult(
            durable=self.durable_capture,
            selections=selected,
            skipped_unversioned_hits=skipped,
        )

    def context_selection_for_run(
        self,
        employee_id: str,
        beat_run_id: str,
    ) -> tuple[ContextAtomSelection, ...]:
        return self._selections.get((employee_id, beat_run_id), ())

    def record_landed_selection(
        self,
        employee_id: str,
        beat_run_id: str,
        *,
        outcome_phase: LandedOutcomePhase,
        landed_at: datetime,
    ) -> tuple[AppliedAtomEdge, ...]:
        self.call_order.append("landed")
        if self.recording_conflict is not None:
            raise self.recording_conflict
        if self.fail_recording:
            raise RuntimeError("postgres applied-edge recorder unavailable")
        selections = self.context_selection_for_run(employee_id, beat_run_id)
        self.landed_calls.append(
            _LandedSelectionCall(
                employee_id,
                beat_run_id,
                outcome_phase,
                landed_at,
                selections,
            )
        )
        edges = tuple(
            AppliedAtomEdge(
                employee_id=selection.employee_id,
                key=selection.key,
                revision=selection.revision,
                beat_run_id=selection.beat_run_id,
                outcome_phase=outcome_phase,
                landed_at=landed_at,
            )
            for selection in selections
        )
        self.recorded_edges.extend(edges)
        return edges

    def has_fresh_episodes(self, employee_id: str) -> bool:
        del employee_id
        return False


class _UnavailableSealLattice:
    """Typed failure seam for the first process in the PostgreSQL restart test."""

    def record_landed_selection(
        self,
        employee_id: str,
        beat_run_id: str,
        *,
        outcome_phase: LandedOutcomePhase,
        landed_at: datetime,
    ) -> NoReturn:
        del employee_id, beat_run_id, outcome_phase, landed_at
        raise RuntimeError("first Lattice process is unavailable")


class _EmptyEpisodes:
    def records_for(self, employee_id: str) -> tuple[RawEpisode, ...]:
        del employee_id
        return ()

    def count_for(self, employee_id: str) -> int:
        del employee_id
        return 0


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


class _HarnessStub:
    def __init__(self) -> None:
        self.hooks: list[object] = []

    def register_hook(self, hook: object) -> None:
        self.hooks.append(hook)


@dataclass
class _HarnessBuildCapture:
    registry: ToolRegistry | None = None
    harness: _HarnessStub = field(default_factory=_HarnessStub)

    def build_harness(self, **kwargs: object) -> _HarnessStub:
        registry = kwargs.get("registry")
        if not isinstance(registry, ToolRegistry):
            raise AssertionError("factory did not provide a tool registry")
        self.registry = registry
        return self.harness


class _Beat:
    def __init__(self, disposition: BeatDisposition, *, working_dir: Path | None = None) -> None:
        self._disposition = disposition
        self._working_dir = working_dir

    @property
    def working_dir(self) -> Path | None:
        return self._working_dir

    async def run_task(self, **_: object) -> BeatOutcome:
        return BeatOutcome(
            passed=self._disposition is BeatDisposition.PASSED,
            disposition=self._disposition,
            outcome={},
            summary="beat complete",
        )


def _hit(
    employee_id: str,
    *,
    revision: int,
    key: str = "engineering.retry",
) -> ContextAtomHit:
    atom = Atom(
        key=key,
        value="Retry transient requests with bounded backoff.",
        employee_id=employee_id,
        source_run_ids=("prior-run",),
        created_at=_NOW,
    )
    return ContextAtomHit(employee_id=employee_id, key=atom.key, revision=revision, atom=atom)


def _runtime(lattice: _RecordingLattice) -> LatticeRuntime:
    return LatticeRuntime(lattice=cast(Lattice, lattice))


def _tool_context(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="session")


async def test_context_tool_captures_the_exact_revision_once_and_cached_call_adds_nothing(
    tmp_path: Path,
) -> None:
    run_id = "run-exact"
    hit = _hit("ada", revision=7)
    lattice = _RecordingLattice({("ada", "retry"): ContextResult("retry guidance", (hit,))})
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    BeatContext(task_id="task-1", run_id=run_id, employee_id="ada").write(worktree)
    tool = LatticeContextTool(cast(Lattice, lattice), durable_selection_journal=True)

    first, duplicate = await asyncio.gather(
        tool.execute({"query": "retry"}, _tool_context(worktree)),
        tool.execute({"query": "retry"}, _tool_context(worktree)),
    )

    assert first.is_error is False
    assert duplicate.is_error is False
    assert lattice.context_selection_for_run("ada", run_id) == (
        ContextAtomSelection("ada", run_id, hit.key, 7),
    )
    assert lattice.capture_calls == [("ada", run_id)]
    assert lattice.context_calls == 1


async def test_distinct_queries_form_one_exact_beat_selection_union(tmp_path: Path) -> None:
    run_id = "run-union"
    retry = _hit("ada", revision=2)
    timeout = _hit("ada", revision=5, key="engineering.timeout")
    lattice = _RecordingLattice(
        {
            ("ada", "retry"): ContextResult("retry", (retry,)),
            ("ada", "timeout"): ContextResult("timeout", (timeout,)),
        }
    )
    worktree = tmp_path / "union"
    worktree.mkdir()
    BeatContext(task_id="task-union", run_id=run_id, employee_id="ada").write(worktree)
    tool = LatticeContextTool(cast(Lattice, lattice), durable_selection_journal=True)

    await tool.execute({"query": "retry"}, _tool_context(worktree))
    await tool.execute({"query": "timeout"}, _tool_context(worktree))

    selections = lattice.context_selection_for_run("ada", run_id)
    assert [(selection.key, selection.revision) for selection in selections] == [
        ("engineering.retry", 2),
        ("engineering.timeout", 5),
    ]


@pytest.mark.parametrize("failure", ["exception", "not_durable", "unversioned", "mixed"])
async def test_context_tool_withholds_content_until_exact_selection_is_durable(
    failure: str, tmp_path: Path
) -> None:
    revision = None if failure == "unversioned" else 4
    atom = _hit("ada", revision=4).atom
    hit = ContextAtomHit(employee_id="ada", key=atom.key, revision=revision, atom=atom)
    hits = (hit,)
    if failure == "mixed":
        unversioned = _hit("ada", revision=1, key="engineering.timeout")
        hits = (
            hit,
            ContextAtomHit(
                employee_id="ada",
                key=unversioned.key,
                revision=None,
                atom=unversioned.atom,
            ),
        )
    lattice = _RecordingLattice({("ada", "retry"): ContextResult("secret guidance", hits)})
    lattice.fail_capture = failure == "exception"
    lattice.durable_capture = failure != "not_durable"
    worktree = tmp_path / failure
    worktree.mkdir()
    BeatContext(task_id="task-1", run_id="run-fail", employee_id="ada").write(worktree)
    tool = LatticeContextTool(cast(Lattice, lattice), durable_selection_journal=True)

    result = await tool.execute({"query": "retry"}, _tool_context(worktree))

    assert result.is_error is True
    assert "secret guidance" not in result.content
    assert "no context was disclosed" in result.content
    assert lattice.capture_calls == [("ada", "run-fail")]
    assert (
        "lattice_context.capture_selection"
        in (worktree / ".harness" / "lattice-error.json").read_text()
    )


async def test_factory_injected_context_tool_reaches_scheduler_without_event_bus(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hit = _hit("piper", revision=13)
    lattice = _RecordingLattice({("piper", "retry"): ContextResult("retry", (hit,))})
    runtime = _runtime(lattice)
    build_capture = _HarnessBuildCapture()
    monkeypatch.setattr(harness_factory_module.dream, "build_harness", build_capture.build_harness)

    def legacy_lattice(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise AssertionError("injected runtime must not construct a legacy lattice")

    monkeypatch.setattr(harness_factory_module, "build_lattice_for_chorus", legacy_lattice)
    factory = harness_factory_module.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
        lattice_runtime=runtime,
    )
    materialized = factory.materialize(Employee(id="piper", name="Piper", role="pm"))
    assert build_capture.registry is not None
    tool = build_capture.registry.get("lattice_context")
    assert tool is not None

    scheduler, _, _, wake, run_id, task_id = _scheduled_beat(
        ledger,
        disposition=BeatDisposition.PASSED,
        employee_id="piper",
        employee_role="pm",
        working_dir=materialized.working_dir,
        runtime=runtime,
    )
    BeatContext(task_id=task_id, run_id=run_id, employee_id="piper").write(materialized.working_dir)
    result = await tool.execute({"query": "retry"}, _tool_context(materialized.working_dir))
    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    assert result.is_error is False
    assert lattice.call_order == ["capture", "landed"]
    assert lattice.recorded_edges[0].revision == hit.revision
    assert lattice.recorded_edges[0].outcome_phase is LandedOutcomePhase.TERMINAL_PASS


async def test_durable_selection_journal_isolates_concurrent_runs(tmp_path: Path) -> None:
    lattice = _RecordingLattice(
        {
            ("ada", "retry"): ContextResult("retry", (_hit("ada", revision=3),)),
            ("bex", "retry"): ContextResult("retry", (_hit("bex", revision=11),)),
        }
    )
    tool = LatticeContextTool(cast(Lattice, lattice), durable_selection_journal=True)
    ada_dir, bex_dir = tmp_path / "ada", tmp_path / "bex"
    ada_dir.mkdir()
    bex_dir.mkdir()
    BeatContext(task_id="task-a", run_id="run-a", employee_id="ada").write(ada_dir)
    BeatContext(task_id="task-b", run_id="run-b", employee_id="bex").write(bex_dir)

    await asyncio.gather(
        tool.execute({"query": "retry"}, _tool_context(ada_dir)),
        tool.execute({"query": "retry"}, _tool_context(bex_dir)),
    )

    assert lattice.context_selection_for_run("ada", "run-a")[0].revision == 3
    assert lattice.context_selection_for_run("bex", "run-b")[0].revision == 11


async def test_scheduler_records_exact_context_with_terminal_pass_phase(ledger: Ledger) -> None:
    scheduler, _runtime, lattice, wake, run_id, _task_id = _scheduled_beat(
        ledger, disposition=BeatDisposition.PASSED
    )
    hit = _hit("ada", revision=9)
    lattice.capture_context_selection("ada", ContextResult("retry", (hit,)), beat_run_id=run_id)

    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    assert lattice.recorded_edges[0].revision == 9
    assert lattice.recorded_edges[0].outcome_phase is LandedOutcomePhase.TERMINAL_PASS
    assert lattice.recorded_edges[0].landed_at == _NOW


async def test_scheduler_records_rework_phase_and_skips_runs_without_context(
    ledger: Ledger,
) -> None:
    scheduler, _runtime, lattice, wake, run_id, _task_id = _scheduled_beat(
        ledger, disposition=BeatDisposition.DOD_FAILED
    )
    hit = _hit("ada", revision=10)
    lattice.capture_context_selection("ada", ContextResult("retry", (hit,)), beat_run_id=run_id)

    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    assert lattice.recorded_edges[0].outcome_phase is LandedOutcomePhase.NEEDS_REWORK
    assert lattice.recorded_edges[0].revision == 10

    (
        no_context_scheduler,
        _runtime,
        no_context_lattice,
        no_context_wake,
        no_context_run,
        _task_id,
    ) = _scheduled_beat(ledger, disposition=BeatDisposition.PASSED, suffix="no-context")
    await no_context_scheduler.run_beat(no_context_wake, run_id=no_context_run, now=_NOW)
    assert no_context_lattice.recorded_edges == []
    assert no_context_lattice.landed_calls[0].selections == ()


async def test_recorder_failure_logs_and_leaves_run_context_recoverable(
    ledger: Ledger, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    scheduler, _runtime, lattice, wake, run_id, _task_id = _scheduled_beat(
        ledger, disposition=BeatDisposition.PASSED, working_dir=worktree
    )
    lattice.fail_recording = True
    hit = _hit("ada", revision=12)
    lattice.capture_context_selection("ada", ContextResult("retry", (hit,)), beat_run_id=run_id)

    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    assert "lattice APPLIED selection sealing failed" in caplog.text
    assert lattice.context_selection_for_run("ada", run_id)[0].revision == 12
    pending = ledger.lattice_selection_seals.get(run_id)
    assert pending is not None
    assert pending.attempt_count == 1
    assert pending.next_attempt_at == _NOW + timedelta(seconds=1)
    assert pending.last_error == "RuntimeError: Lattice selection seal failed"

    await scheduler.tick(_NOW + timedelta(milliseconds=500))
    assert lattice.call_order.count("landed") == 1

    await scheduler.tick(_NOW + timedelta(seconds=1))
    assert lattice.call_order.count("landed") == 2
    assert caplog.text.count("lattice APPLIED selection sealing failed") == 2

    await scheduler.tick(_NOW + timedelta(seconds=2, milliseconds=500))
    assert lattice.call_order.count("landed") == 2

    lattice.fail_recording = False
    await scheduler.tick(_NOW + timedelta(seconds=3))

    assert lattice.recorded_edges[0].revision == 12
    assert lattice.recorded_edges[0].outcome_phase is LandedOutcomePhase.TERMINAL_PASS
    assert lattice.call_order.count("landed") == 3
    sealed = ledger.lattice_selection_seals.get(run_id)
    assert sealed is not None and sealed.sealed_at == _NOW + timedelta(seconds=3)


async def test_process_death_after_landed_commit_recovers_outbox_on_new_scheduler(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduler, runtime, lattice, wake, run_id, _task_id = _scheduled_beat(
        ledger, disposition=BeatDisposition.PASSED, suffix="commit-crash"
    )
    lattice.capture_context_selection(
        "adacommit-crash",
        ContextResult("retry", (_hit("adacommit-crash", revision=14),)),
        beat_run_id=run_id,
    )

    def die_after_commit(seal: object, *, now: datetime) -> NoReturn:
        del seal, now
        raise SystemExit("simulated process death after landed commit")

    monkeypatch.setattr(scheduler, "_attempt_enqueued_lattice_selection", die_after_commit)
    with pytest.raises(SystemExit, match="simulated process death"):
        await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    committed_run = ledger.runs.get(run_id)
    pending = ledger.lattice_selection_seals.get(run_id)
    assert committed_run is not None and committed_run.status is RunStatus.SUCCEEDED
    assert pending is not None and pending.attempt_count == 0

    restarted = Scheduler(
        ledger=ledger,
        lattice_runtime=LatticeRuntime(runtime.lattice),
        clock=lambda: _NOW,
    )
    await restarted.tick(_NOW)

    assert lattice.recorded_edges[0].revision == 14
    sealed = ledger.lattice_selection_seals.get(run_id)
    assert sealed is not None and sealed.sealed_at == _NOW


@pytest.mark.parametrize(
    "conflict",
    [
        AppliedEdgeConflictError("persisted APPLIED header differs"),
        ContextSelectionConflictError("persisted selection lineage differs"),
    ],
)
async def test_exact_lattice_conflict_is_terminal_and_observable(
    ledger: Ledger, conflict: Exception
) -> None:
    scheduler, _runtime, lattice, wake, run_id, _task_id = _scheduled_beat(
        ledger, disposition=BeatDisposition.PASSED, suffix="conflict"
    )
    lattice.recording_conflict = conflict

    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    terminal = ledger.lattice_selection_seals.get(run_id)
    assert terminal is not None
    assert terminal.attempt_count == 1
    assert terminal.next_attempt_at is None
    assert terminal.terminal_at == _NOW
    assert terminal.last_error == f"{type(conflict).__name__}: Lattice selection seal failed"

    await scheduler.tick(_NOW + timedelta(days=1))
    assert lattice.call_order.count("landed") == 1


async def test_enqueue_failure_rolls_back_the_whole_landed_commit_and_raises(
    ledger: Ledger,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events = _EventRecorder()
    scheduler, _runtime, _lattice, wake, run_id, task_id = _scheduled_beat(
        ledger,
        disposition=BeatDisposition.PASSED,
        suffix="enqueue-fail",
        event_bus=events,
    )

    def fail_enqueue(seal: object) -> NoReturn:
        del seal
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(ledger.lattice_selection_seals, "enqueue", fail_enqueue)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    task = ledger.tasks.get(task_id)
    rolled_back_run = ledger.runs.get(run_id)
    assert task is not None and task.status is TaskStatus.IN_PROGRESS
    assert rolled_back_run is not None and rolled_back_run.status is RunStatus.RUNNING
    assert ledger.lattice_selection_seals.get(run_id) is None
    assert not any(event.kind is EventKind.OUTCOME_LANDED for event in events.events)
    assert "failed to durably enqueue Lattice selection seal" in caplog.text


async def test_landed_event_and_selection_share_fresh_completion_time(ledger: Ledger) -> None:
    dispatched_at = _NOW
    landed_at = _NOW + timedelta(minutes=7)
    lattice = _RecordingLattice()
    runtime = _runtime(lattice)
    events = _EventRecorder()
    scheduler, wake, run_id, _task_id = _scheduled_runtime_beat(
        ledger,
        runtime=runtime,
        disposition=BeatDisposition.PASSED,
        employee_id="ada",
        employee_role="backend_engineer",
        suffix="delayed",
        clock=lambda: landed_at,
        event_bus=events,
    )

    await scheduler.run_beat(wake, run_id=run_id, now=dispatched_at)

    outcome_event = next(event for event in events.events if event.kind is EventKind.OUTCOME_LANDED)
    assert outcome_event.at == landed_at
    assert lattice.landed_calls[0].landed_at == landed_at


async def test_postgres_outbox_survives_scheduler_restart_and_seals_exact_selection(
    pg_database: str,
    tmp_path: Path,
) -> None:
    with psycopg.connect(pg_database, autocommit=True) as admin:
        for migration in load_migrations():
            admin.execute(migration.sql)
    company_id = uuid.uuid4()
    company_text = str(company_id)
    employee_id = "adapg-restart"
    suffix = "pg-restart"
    run_id = uid(f"run{suffix}")
    task_id = uid(f"task{suffix}")
    worktree = tmp_path / "postgres-restart"
    worktree.mkdir()
    BeatContext(task_id=task_id, run_id=run_id, employee_id=employee_id).write(worktree)

    first_ledger = Ledger.open(pg_database, company_id=company_text)
    failing_runtime = LatticeRuntime(cast(Lattice, _UnavailableSealLattice()))
    first_scheduler, wake, actual_run_id, actual_task_id = _scheduled_runtime_beat(
        first_ledger,
        runtime=failing_runtime,
        disposition=BeatDisposition.PASSED,
        employee_id=employee_id,
        employee_role="backend_engineer",
        suffix=suffix,
        working_dir=worktree,
        clock=lambda: _NOW,
    )
    assert (actual_run_id, actual_task_id) == (run_id, task_id)

    with PostgresLatticeStore.open(pg_database, company_id=company_id) as first_store:
        first_store.atoms.write(_hit(employee_id, revision=1).atom)
        first_lattice = first_store.build_lattice(episodes=_EmptyEpisodes())
        tool = LatticeContextTool(first_lattice, durable_selection_journal=True)
        result = await tool.execute({"query": "retry"}, _tool_context(worktree))
        assert result.is_error is False
        selected = first_lattice.context_selection_for_run(employee_id, run_id)
        assert selected[0].revision == 1

    await first_scheduler.run_beat(wake, run_id=run_id, now=_NOW - timedelta(minutes=1))
    pending = first_ledger.lattice_selection_seals.get(run_id)
    assert pending is not None
    assert pending.attempt_count == 1
    assert pending.sealed_at is None
    assert pending.next_attempt_at == _NOW + timedelta(seconds=1)
    first_ledger.close()

    restarted_ledger = Ledger.open(pg_database, company_id=company_text)
    try:
        with PostgresLatticeStore.open(pg_database, company_id=company_id) as restarted_store:
            restarted_lattice = restarted_store.build_lattice(episodes=_EmptyEpisodes())
            restarted_scheduler = Scheduler(
                ledger=restarted_ledger,
                lattice_runtime=LatticeRuntime(restarted_lattice),
                clock=lambda: _NOW + timedelta(seconds=1),
            )

            await restarted_scheduler.tick(_NOW + timedelta(seconds=1))

            edges = restarted_store.applied_edges.list_for_run(employee_id, run_id)
            assert len(edges) == 1
            assert edges[0].revision == 1
            assert edges[0].outcome_phase is LandedOutcomePhase.TERMINAL_PASS
            assert edges[0].landed_at == _NOW

        sealed = restarted_ledger.lattice_selection_seals.get(run_id)
        assert sealed is not None
        assert sealed.sealed_at == _NOW + timedelta(seconds=1)
        assert sealed.outcome_phase.value == LandedOutcomePhase.TERMINAL_PASS.value
        assert sealed.landed_at == _NOW

        with psycopg.connect(pg_database) as admin:
            header = admin.execute(
                "SELECT outcome_phase, landed_at, selected_count "
                "FROM lattice_atom_applied_beat "
                "WHERE company_id = %s AND employee_id = %s AND beat_run_id = %s",
                (company_text, employee_id, run_id),
            ).fetchone()
        assert header == (LandedOutcomePhase.TERMINAL_PASS.value, _NOW, 1)
    finally:
        restarted_ledger.close()


def _scheduled_beat(
    ledger: Ledger,
    *,
    disposition: BeatDisposition,
    suffix: str = "",
    working_dir: Path | None = None,
    employee_id: str | None = None,
    employee_role: str = "backend_engineer",
    runtime: LatticeRuntime | None = None,
    event_bus: EventSink | None = None,
) -> tuple[Scheduler, LatticeRuntime, _RecordingLattice, Wake, str, str]:
    lattice = _RecordingLattice() if runtime is None else cast(_RecordingLattice, runtime.lattice)
    runtime = _runtime(lattice) if runtime is None else runtime
    scheduler, wake, run_id, task_id = _scheduled_runtime_beat(
        ledger,
        runtime=runtime,
        disposition=disposition,
        suffix=suffix,
        working_dir=working_dir,
        employee_id=employee_id or f"ada{suffix}",
        employee_role=employee_role,
        clock=lambda: _NOW,
        event_bus=event_bus,
    )
    return scheduler, runtime, lattice, wake, run_id, task_id


def _scheduled_runtime_beat(
    ledger: Ledger,
    *,
    runtime: LatticeRuntime,
    disposition: BeatDisposition,
    employee_id: str,
    employee_role: str,
    suffix: str = "",
    working_dir: Path | None = None,
    clock: Callable[[], datetime],
    event_bus: EventSink | None = None,
) -> tuple[Scheduler, Wake, str, str]:
    task_id = uid(f"task{suffix}")
    run_id = uid(f"run{suffix}")
    wake_id = uid(f"wake{suffix}")
    ledger.employees.create(Employee(id=employee_id, name="Ada", role=employee_role))
    ledger.tasks.submit(
        Task(
            id=task_id,
            intent="ship",
            status=TaskStatus.TODO,
            assignee_employee_id=employee_id,
        )
    )
    ledger.dod.create(task_id, Verifier.command("true"))
    assert ledger.tasks.checkout(task_id, employee_id=employee_id, run_id=run_id)
    ledger.wakes.enqueue(
        Wake(
            id=wake_id,
            employee_id=employee_id,
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": task_id},
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=_Beat(disposition, working_dir=working_dir),
        lattice_runtime=runtime,
        clock=clock,
        event_bus=event_bus,
    )
    return scheduler, wake, run_id, task_id
