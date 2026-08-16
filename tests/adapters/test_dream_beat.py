"""The dream beat adapter — RunTaskResult → BeatOutcome (spec 03 §3, spec 05 dream seam).

``to_beat_outcome`` is the verdict rule: a beat *passed* iff dream's plan fully completed (every
ledger step ``done``). ``DreamBeatRunner`` runs one beat through a dream Harness and lands that
verdict, turning any harness error into a clean ``passed=False`` rather than an unhandled crash.
The adapter never imports dream — it reads the result through narrow protocols, so these fakes stand
in for dream's real types.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from dream.runner.events import RunTaskEvent
from tests.adapters._dream_events import (
    RoleSessionRecovered,
    contract_written,
    evaluator_completed,
    planner_started,
    role_session_closed,
    role_session_recovered,
    role_text,
    role_tool_result,
    role_tool_start,
    spawn_subagent_result,
    spawn_subagent_start,
    task_completed,
    task_started,
)

from chorus.adapters import DreamBeatRunner, ModelRate, TokenPricing, to_beat_outcome
from chorus.events import Event, EventKind
from chorus.heartbeat import (
    BeatDisposition,
    SessionRecoveryAction,
    SessionRecoveryNotice,
    SessionRecoveryReason,
)
from chorus.heartbeat._todo_flush import read_todo_flush_nudge
from chorus.ledger import dream_session_key_for_task
from chorus.outcomes import VerificationStep
from chorus.testing import uid

pytestmark = pytest.mark.unit


# -- fakes shaped like dream's RunTaskResult (the read-only surface the adapter consumes) ----------


@dataclass(frozen=True)
class _Step:
    status: str


@dataclass(frozen=True)
class _Ledger:
    steps: tuple[_Step, ...]


@dataclass(frozen=True)
class _Sprint:
    outcome: str | None
    evaluation: object | None = None


@dataclass(frozen=True)
class _Evaluation:
    notes: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class _Result:
    final_ledger: _Ledger
    sprints: tuple[_Sprint, ...] = field(default_factory=tuple)
    usage_by_model: dict[str, _Usage] = field(default_factory=dict)


def _result(
    *statuses: str,
    sprints: tuple[str | None, ...] = (),
    usage_by_model: dict[str, _Usage] | None = None,
) -> _Result:
    return _Result(
        final_ledger=_Ledger(steps=tuple(_Step(s) for s in statuses)),
        sprints=tuple(_Sprint(o) for o in sprints),
        usage_by_model=usage_by_model or {},
    )


class _FakeRunTaskError(Exception):
    """Shaped like ``dream.RunTaskError``: a stable ``code`` and a typed ``phase``."""

    code = "dream.run_task"

    def __init__(self, message: str, *, phase: str) -> None:
        super().__init__(message)
        self.phase = phase


class _FakeTaskCancelled(Exception):
    """Shaped like ``dream.TaskCancelled``: the stable cooperative-cancel ``code``."""

    code = "dream.cancelled"


class _FakeHarness:
    """A stand-in dream Harness: returns a canned result, or raises a canned error.

    When ``events`` is given it replays them through the ``observer`` dream is handed, so the bridge's
    typed RunTaskEvent -> chorus-Event translation can be exercised without a real engine.
    """

    def __init__(
        self,
        *,
        result: _Result | None = None,
        error: BaseException | None = None,
        events: tuple[RunTaskEvent | RoleSessionRecovered, ...] = (),
    ) -> None:
        self._result = result
        self._error = error
        self._events = events
        self.calls: list[str] = []
        self.verification_steps: tuple[dict[str, str], ...] = ()
        self.observer: object = None
        self.max_sprints: int | None = None
        self.harness_dir: str | Path | None = None
        self.plan_admission: object = None
        self.session_scope: str | None = None
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification_steps: tuple[dict[str, str], ...] = (),
        observer: object = None,
        max_sprints: int | None = None,
        harness_dir: str | Path | None = None,
        rubric: str | None = None,
        plan_admission: object = None,
        session_scope: str | None = None,
    ) -> _Result:
        self.calls.append(task_id)
        self.verification_steps = verification_steps
        self.observer = observer
        self.max_sprints = max_sprints
        self.harness_dir = harness_dir
        self.plan_admission = plan_admission
        self.session_scope = session_scope
        if observer is not None:
            for event in self._events:
                observer.on_event(event)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class _HangingHarness:
    async def run_task(self, **kwargs: object) -> _Result:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _MeteringHangingHarness:
    """Hangs after emitting one meterable role.session.closed event."""

    async def run_task(self, **kwargs: object) -> _Result:
        observer = kwargs.get("observer")
        if observer is not None:
            observer.on_event(
                role_session_closed(model="gpt-test", input_tokens=1000, output_tokens=500)
            )
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_run_task_timeout_prices_partial_usage() -> None:
    pricing = TokenPricing(
        rates={"gpt-test": ModelRate(input_cents_per_mtok=100, output_cents_per_mtok=1000)}
    )
    outcome = await DreamBeatRunner(
        _MeteringHangingHarness(), timeout_s=0.05, pricing=pricing
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.disposition is BeatDisposition.ERRORED
    assert outcome.cost_cents > 0
    assert outcome.input_tokens == 1000
    assert outcome.output_tokens == 500


async def test_run_task_timeout_is_an_errored_outcome() -> None:
    outcome = await DreamBeatRunner(_HangingHarness(), timeout_s=0.01).run_task(
        task_id=uid("t1"), intent="x"
    )

    assert outcome.disposition is BeatDisposition.ERRORED
    assert "TimeoutError" in str(outcome.outcome["error"])


async def test_run_task_timeout_can_land_when_local_verification_passes(tmp_path: Path) -> None:
    (tmp_path / "artifact.md").write_text("done\n", encoding="utf-8")
    command = subprocess.list2cmdline(
        [sys.executable, "-c", "from pathlib import Path; assert Path('artifact.md').is_file()"]
    )

    outcome = await DreamBeatRunner(
        _HangingHarness(), timeout_s=0.01, working_dir=tmp_path
    ).run_task(task_id=uid("t1"), intent="x", verification=(VerificationStep(command),))

    assert outcome.passed is True
    assert outcome.disposition is BeatDisposition.PASSED
    assert outcome.outcome["verified_after_timeout"] is True


async def test_run_task_can_land_when_local_verification_passes_after_incomplete_result(
    tmp_path: Path,
) -> None:
    (tmp_path / "artifact.md").write_text("done\n", encoding="utf-8")
    command = subprocess.list2cmdline(
        [sys.executable, "-c", "from pathlib import Path; assert Path('artifact.md').is_file()"]
    )

    outcome = await DreamBeatRunner(
        _FakeHarness(result=_result("blocked", sprints=("needs-changes",))),
        working_dir=tmp_path,
    ).run_task(task_id=uid("t1"), intent="x", verification=(VerificationStep(command),))

    assert outcome.passed is True
    assert outcome.disposition is BeatDisposition.PASSED
    assert outcome.outcome["verified_after_incomplete_dream_result"] is True
    assert outcome.outcome["steps_blocked"] == 1


async def test_run_task_passes_working_dir_as_harness_dir(tmp_path: Path) -> None:
    harness = _FakeHarness(result=_result("done"))

    await DreamBeatRunner(harness, working_dir=tmp_path).run_task(task_id=uid("t1"), intent="x")


async def test_dream_uses_stable_chorus_task_id_with_resume(tmp_path: Path) -> None:
    # Hermes-simple: reuse chorus task_id + PlanAdmission.RESUME so needs-changes
    # carry-forward survives ticks. Fresh per-beat run_ids cold-started the planner.
    from dream.runner import PlanAdmission

    harness = _FakeHarness(result=_result("done"))
    await DreamBeatRunner(harness, working_dir=tmp_path, employee_id=uid("e")).run_task(
        task_id="task_M", intent="x", run_id=uid("run_42")
    )
    assert harness.calls == ["task_M"]
    assert harness.plan_admission is PlanAdmission.RESUME


async def test_without_a_run_id_dream_still_uses_the_task_id(tmp_path: Path) -> None:
    from dream.runner import PlanAdmission

    harness = _FakeHarness(result=_result("done"))
    await DreamBeatRunner(harness, working_dir=tmp_path).run_task(task_id="task_M", intent="x")
    assert harness.calls == ["task_M"]
    assert harness.plan_admission is PlanAdmission.RESUME


async def test_every_beat_on_a_task_addresses_the_same_dream_session(tmp_path: Path) -> None:
    """The beat hands dream the task's session key, and the same one every time.

    ``PlanAdmission.RESUME`` above keeps the *plan* across beats; the scope keeps
    the *conversation* that produced it. Without it each beat would re-open the
    planner, generator, and evaluator on empty threads and re-derive what the
    last beat already worked out.
    """
    harness = _FakeHarness(result=_result("done"))
    runner = DreamBeatRunner(harness, working_dir=tmp_path, employee_id=uid("e"))

    await runner.run_task(task_id="task_M", intent="first", run_id=uid("run_1"))
    first_scope = harness.session_scope
    await runner.run_task(task_id="task_M", intent="second", run_id=uid("run_2"))

    assert first_scope == dream_session_key_for_task("task_M")
    assert harness.session_scope == first_scope


async def test_bound_control_plane_session_scope_overrides_task_fallback(tmp_path: Path) -> None:
    harness = _FakeHarness(
        result=_result("done"),
        events=(role_text(text="resumed"),),
    )
    runner = DreamBeatRunner(harness, working_dir=tmp_path, employee_id=uid("e"))
    scoped = runner.for_session_scope("session-control-plane-1")
    assert scoped.working_dir == tmp_path

    seen: list[Event] = []
    await scoped.run_task(
        task_id="task_M", intent="resume", run_id=uid("run_1"), observer=seen.append
    )

    assert harness.session_scope == "session-control-plane-1"
    assert [event.kind for event in seen] == [EventKind.RUN_TEXT]
    assert seen[0].payload["dream_kind"] == "role.text"


async def test_run_task_writes_the_beat_context_for_capability_tools(tmp_path: Path) -> None:
    # A capability tool (e.g. the manager's decompose) reads which task/run it acts for from the
    # per-beat context the runner drops into the worktree before invoking dream.
    from chorus.heartbeat import BeatContext

    harness = _FakeHarness(result=_result("done"))
    await DreamBeatRunner(harness, working_dir=tmp_path, employee_id="mgr").run_task(
        task_id="M", intent="x", run_id=uid("run1")
    )

    assert BeatContext.read(tmp_path) == BeatContext(
        task_id="M", run_id=uid("run1"), employee_id="mgr"
    )

    assert harness.harness_dir == tmp_path / ".harness"


# -- to_beat_outcome: the verdict rule -------------------------------------------------------------


def test_passed_when_every_step_done() -> None:
    outcome = to_beat_outcome(_result("done", "done", sprints=("pass", "pass")))
    assert outcome.passed is True
    assert outcome.outcome["steps_total"] == 2
    assert outcome.outcome["steps_done"] == 2
    assert outcome.outcome["sprint_outcomes"] == ["pass", "pass"]


def test_typed_evaluation_notes_carry_into_the_beat_outcome() -> None:
    result = _Result(
        final_ledger=_Ledger((_Step("done"),)),
        sprints=(
            _Sprint("needs-changes", _Evaluation("cover retries", ("missing edge case",))),
        ),
    )

    outcome = to_beat_outcome(result)

    assert outcome.evaluator_notes == ("cover retries", "missing edge case")


async def test_run_task_records_reasoning_and_actions_into_raw_record() -> None:
    harness = _FakeHarness(
        result=_result("done"),
        events=(
            role_text(text="I chose a salted hashlib password hash"),
            role_tool_start(tool="write_file", input={"path": "auth/service.py"}),
            role_tool_result(tool="write_file", content="wrote 42 lines"),
            planner_started(task_id=uid("t")),  # lifecycle noise — must NOT be recorded
        ),
    )
    outcome = await DreamBeatRunner(harness).run_task(
        task_id=uid("t"), intent="build auth", run_id=uid("r1")
    )
    assert "salted hashlib password hash" in outcome.raw_record  # the reasoning
    assert "auth/service.py" in outcome.raw_record  # the action + its args
    assert "wrote 42 lines" in outcome.raw_record  # the tool result
    assert "planner.started" not in outcome.raw_record  # lifecycle excluded


async def test_run_task_records_reasoning_even_on_failure() -> None:
    harness = _FakeHarness(
        error=_FakeRunTaskError("boom", phase="plan"),
        events=(role_text(text="tried the pool bump, it regressed"),),
    )
    outcome = await DreamBeatRunner(harness).run_task(
        task_id=uid("t"), intent="x", run_id=uid("r1")
    )
    assert outcome.passed is False
    assert "tried the pool bump" in outcome.raw_record  # a failed beat still keeps its account


def test_not_passed_when_a_step_is_unfinished() -> None:
    assert to_beat_outcome(_result("done", "in_progress")).passed is False


def test_not_passed_when_a_step_is_blocked() -> None:
    outcome = to_beat_outcome(_result("done", "blocked"))
    assert outcome.passed is False
    assert outcome.outcome["steps_blocked"] == 1


def test_empty_plan_is_not_passed() -> None:
    # no steps means nothing was actually completed — never a silent pass
    assert to_beat_outcome(_result()).passed is False


# -- cost: the beat's spend, priced from dream's metered usage -------------------------------------


def test_unpriced_beat_costs_zero() -> None:
    result = _result("done", usage_by_model={"gpt-x": _Usage(input_tokens=1_000_000)})
    assert to_beat_outcome(result).cost_cents == 0  # no pricing supplied


def test_priced_beat_carries_real_cost() -> None:
    pricing = TokenPricing(rates={"gpt-x": ModelRate(125, 1000)})
    result = _result(
        "done", usage_by_model={"gpt-x": _Usage(input_tokens=1_000_000, output_tokens=200_000)}
    )
    outcome = to_beat_outcome(result, pricing=pricing)
    assert outcome.cost_cents == 325  # 125 + 200
    assert outcome.outcome["cost_cents"] == 325


def test_priced_beat_with_no_usage_costs_zero() -> None:
    pricing = TokenPricing(rates={"gpt-x": ModelRate(125, 1000)})
    assert to_beat_outcome(_result("done"), pricing=pricing).cost_cents == 0


def test_outcome_carries_model_and_token_totals() -> None:
    result = _result("done", usage_by_model={"gpt-x": _Usage(input_tokens=100, output_tokens=40)})
    outcome = to_beat_outcome(result)  # tokens are surfaced regardless of pricing
    assert outcome.model == "gpt-x"
    assert outcome.input_tokens == 100
    assert outcome.output_tokens == 40


def test_multiple_models_are_joined_and_tokens_summed() -> None:
    result = _result(
        "done",
        usage_by_model={
            "gpt-4": _Usage(input_tokens=10, output_tokens=1),
            "gpt-5.2": _Usage(input_tokens=20, output_tokens=2),
        },
    )
    outcome = to_beat_outcome(result)
    assert outcome.model == "gpt-4+gpt-5.2"  # sorted, joined
    assert outcome.input_tokens == 30
    assert outcome.output_tokens == 3


# -- DreamBeatRunner: run one beat through the harness ---------------------------------------------


async def test_run_task_maps_a_completed_plan_to_passed() -> None:
    harness = _FakeHarness(result=_result("done"))
    runner = DreamBeatRunner(harness)
    outcome = await runner.run_task(task_id=uid("t1"), intent="ship it")
    assert outcome.passed is True
    assert harness.calls == [uid("t1")]
    assert harness.close_calls == 1


async def test_run_task_turns_a_harness_error_into_a_failed_beat() -> None:
    harness = _FakeHarness(error=RuntimeError("provider 500"))
    runner = DreamBeatRunner(harness)
    outcome = await runner.run_task(task_id=uid("t1"), intent="ship it")
    assert outcome.passed is False
    assert outcome.disposition is BeatDisposition.ERRORED  # an unexpected fault is an engine error
    assert "provider 500" in str(outcome.outcome["error"])
    assert outcome.outcome["phase"] is None  # a non-dream error carries no phase
    assert harness.close_calls == 1


async def test_run_task_prices_the_beat_when_pricing_is_wired() -> None:
    harness = _FakeHarness(
        result=_result("done", usage_by_model={"gpt-x": _Usage(input_tokens=2_000_000)})
    )
    runner = DreamBeatRunner(harness, pricing=TokenPricing(rates={"gpt-x": ModelRate(125, 1000)}))
    outcome = await runner.run_task(task_id=uid("t1"), intent="ship it")
    assert outcome.cost_cents == 250  # 2 Mtok input * 125 c/Mtok


async def test_run_task_is_unpriced_without_pricing() -> None:
    harness = _FakeHarness(
        result=_result("done", usage_by_model={"gpt-x": _Usage(input_tokens=2_000_000)})
    )
    outcome = await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x")
    assert outcome.cost_cents == 0


async def test_run_task_forwards_the_command_dod_as_verification_steps() -> None:
    harness = _FakeHarness(result=_result("done"))
    runner = DreamBeatRunner(harness)
    await runner.run_task(
        task_id=uid("t1"), intent="ship", verification=(VerificationStep(command="pytest -q"),)
    )
    # dream requires kind ∈ {test, lint, eval}; a chorus Command DoD maps to "eval"
    assert harness.verification_steps == ({"kind": "eval", "command": "pytest -q"},)


async def test_run_task_with_no_verification_passes_none() -> None:
    harness = _FakeHarness(result=_result("done"))
    await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x")
    assert harness.verification_steps == ()


async def test_run_task_bounds_the_dream_sprint_loop_by_default() -> None:
    harness = _FakeHarness(result=_result("done"))

    await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x")

    assert harness.max_sprints == 1


async def test_run_task_forwards_dream_events_to_the_observer() -> None:
    # dream replays its typed event stream through the bridge; chorus witnesses the mapped run.* subset.
    harness = _FakeHarness(
        result=_result("done"),
        events=(
            task_started(task_id=uid("t1"), intent="x"),
            role_text(text="hello"),
            role_tool_start(tool="bash"),
            evaluator_completed(),
            task_completed(task_id=uid("t1")),
        ),
    )
    seen: list[Event] = []
    outcome = await DreamBeatRunner(harness).run_task(
        task_id=uid("t1"), intent="x", observer=seen.append
    )
    assert outcome.passed is True
    assert [e.kind for e in seen] == [
        EventKind.RUN_STARTED,
        EventKind.RUN_TEXT,
        EventKind.RUN_TOOL_USE,
        EventKind.RUN_EVALUATED,
        EventKind.RUN_DONE,
    ]
    text = next(e for e in seen if e.kind is EventKind.RUN_TEXT)
    assert text.task_id == uid("t1")
    assert text.payload["text"] == "hello"
    assert text.payload["dream_kind"] == "role.text"  # the original dream kind is preserved


async def test_run_task_drops_dream_events_without_a_chorus_equivalent() -> None:
    # macro lifecycle kinds have no closed-vocabulary run.* equivalent yet — dropped, not mislabelled.
    harness = _FakeHarness(
        result=_result("done"),
        events=(
            planner_started(task_id=uid("t1")),
            contract_written(),
            role_text(text="kept"),
        ),
    )
    seen: list[Event] = []
    await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x", observer=seen.append)
    assert [e.kind for e in seen] == [EventKind.RUN_TEXT]


async def test_run_task_records_the_account_even_without_a_chorus_observer() -> None:
    # No chorus observer -> no liveness bridge, but the reasoning recorder is always handed to dream so
    # the episodic account is captured regardless of whether anyone is witnessing the run.
    harness = _FakeHarness(
        result=_result("done"), events=(role_text(text="picked X"),)
    )
    outcome = await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x")
    assert "picked X" in outcome.raw_record  # captured with no chorus observer wired


async def test_run_task_captures_session_recovery_without_a_chorus_observer() -> None:
    """Recovery remains observable even when a caller did not wire Chorus eventing."""
    outcome = await DreamBeatRunner(
        _FakeHarness(
            result=_result("done"),
            events=(
                role_session_recovered(
                    session_id="fresh-session",
                    requested_session_id="stale-session",
                    reason="corrupt",
                    action="reset",
                    snapshot_preserved=True,
                ),
            ),
        )
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.session_recovery == SessionRecoveryNotice(
        role="generator",
        session_id="fresh-session",
        requested_session_id="stale-session",
        reason=SessionRecoveryReason.CORRUPT,
        action=SessionRecoveryAction.RESET,
        snapshot_preserved=True,
    )
    assert "role.session.recovered" not in outcome.raw_record


async def test_run_task_forwards_session_recovery_to_the_observer() -> None:
    harness = _FakeHarness(
        result=_result("done"),
        events=(role_session_recovered(reason="corrupt", action="reset", snapshot_preserved=True),),
    )
    seen: list[Event] = []
    outcome = await DreamBeatRunner(harness).run_task(
        task_id=uid("t1"), intent="x", observer=seen.append
    )

    assert outcome.session_recovery is not None
    assert [e.kind for e in seen] == [EventKind.SESSION_RECOVERED]
    assert seen[0].payload["session_id"] == "fresh-session"
    assert seen[0].payload["requested_session_id"] == "stale-session"


async def test_run_task_forwards_resume_recovery_to_the_observer() -> None:
    harness = _FakeHarness(
        result=_result("done"),
        events=(role_session_recovered(reason="corrupt", action="resume", snapshot_preserved=True),),
    )
    seen: list[Event] = []
    outcome = await DreamBeatRunner(harness).run_task(
        task_id=uid("t1"), intent="x", observer=seen.append
    )

    assert outcome.session_recovery is not None
    assert outcome.session_recovery.action is SessionRecoveryAction.RESUME
    assert seen[0].payload["action"] == SessionRecoveryAction.RESUME.value


@pytest.mark.parametrize(
    "event",
    (
        role_session_recovered(reason="unknown", action="reset"),
        role_session_recovered(reason="missing", action="wipe"),
        role_session_recovered(role=""),
        role_session_recovered(session_id=""),
    ),
)
async def test_run_task_ignores_malformed_session_recovery_events(
    event: RoleSessionRecovered,
) -> None:
    outcome = await DreamBeatRunner(
        _FakeHarness(result=_result("done"), events=(event,))
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.passed is True
    assert outcome.session_recovery is None


async def test_run_task_retains_recovery_when_dream_raises() -> None:
    outcome = await DreamBeatRunner(
        _FakeHarness(
            error=_FakeRunTaskError("boom", phase="generator"),
            events=(
                role_session_recovered(
                    reason="working_dir_mismatch",
                    action="reset",
                    snapshot_preserved=True,
                ),
            ),
        )
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.disposition is BeatDisposition.ERRORED
    assert outcome.session_recovery is not None
    assert outcome.session_recovery.reason is SessionRecoveryReason.WORKING_DIR_MISMATCH


async def test_run_task_retains_recovery_when_dream_cancels() -> None:
    outcome = await DreamBeatRunner(
        _FakeHarness(
            error=_FakeTaskCancelled("budget exhausted"),
            events=(role_session_recovered(reason="missing", action="bypass"),),
        )
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.disposition is BeatDisposition.CANCELLED
    assert outcome.session_recovery is not None
    assert outcome.session_recovery.reason is SessionRecoveryReason.MISSING


async def test_run_task_rejects_a_parent_replaced_subagent_artifact(tmp_path: Path) -> None:
    reviewer_output = {
        "cleared": False,
        "findings": [
            {
                "category": "other",
                "severity": "high",
                "location": "links.py:1",
                "detail": "runtime state is committed",
                "fix": "remove it",
            }
        ],
        "evidence": "reviewed the diff",
    }
    (tmp_path / "review_verdict.json").write_text(
        json.dumps({"cleared": True, "findings": [], "evidence": "parent replacement"})
    )
    events = (
        spawn_subagent_start(name="code_reviewer", prompt="Review"),
        spawn_subagent_result(content=json.dumps(reviewer_output)),
    )
    harness = _FakeHarness(result=_result("done"), events=events)

    outcome = await DreamBeatRunner(
        harness,
        working_dir=tmp_path,
        subagent_evidence={"code_reviewer": ("review_verdict.json", {"cleared": True})},
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.passed is False
    assert outcome.outcome["subagent_evidence"] == "failed"
    assert "required claim" in outcome.summary
    assert json.loads((tmp_path / "review_verdict.json").read_text()) == reviewer_output


async def test_run_task_records_and_reuses_valid_subagent_provenance(tmp_path: Path) -> None:
    reviewer_output = {"cleared": True, "findings": [], "evidence": "reviewed the diff"}
    events = (
        spawn_subagent_start(name="code_reviewer", prompt="Review"),
        spawn_subagent_result(content=json.dumps(reviewer_output)),
    )
    requirement = {"code_reviewer": ("review_verdict.json", {"cleared": True})}

    first = await DreamBeatRunner(
        _FakeHarness(result=_result("done"), events=events),
        working_dir=tmp_path,
        subagent_evidence=requirement,
    ).run_task(task_id=uid("t1"), intent="x")
    resumed = await DreamBeatRunner(
        _FakeHarness(result=_result("done")),
        working_dir=tmp_path,
        subagent_evidence=requirement,
    ).run_task(task_id=uid("t1"), intent="resume")

    assert first.passed is True
    assert resumed.passed is True
    assert json.loads((tmp_path / "review_verdict.json").read_text()) == reviewer_output
    assert (tmp_path / ".harness" / "subagent-evidence" / "code_reviewer.json").is_file()


async def test_run_task_rejects_code_changed_after_independent_review(tmp_path: Path) -> None:
    reviewer_output = {"cleared": True, "findings": [], "evidence": "reviewed links.py"}
    (tmp_path / "links.py").write_text("VALUE = 1\n")
    (tmp_path / "review_verdict.json").write_text(json.dumps(reviewer_output))
    events = (
        spawn_subagent_start(name="code_reviewer", prompt="Review"),
        spawn_subagent_result(content=json.dumps(reviewer_output)),
    )

    class _MutatesAfterReview(_FakeHarness):
        async def run_task(self, **kwargs: Any) -> _Result:
            result = await super().run_task(**kwargs)
            (tmp_path / "links.py").write_text("VALUE = 2\n")
            return result

    outcome = await DreamBeatRunner(
        _MutatesAfterReview(result=_result("done"), events=events),
        working_dir=tmp_path,
        subagent_evidence={"code_reviewer": ("review_verdict.json", {"cleared": True})},
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.passed is False
    assert "worktree changed after independent review" in outcome.summary


async def test_run_task_rejects_evidence_subagent_mutating_worktree(tmp_path: Path) -> None:
    reviewer_output = {"cleared": True, "findings": [], "evidence": "reviewed links.py"}
    (tmp_path / "links.py").write_text("VALUE = 1\n")

    class _MutatesDuringReview(_FakeHarness):
        async def run_task(self, **kwargs: Any) -> _Result:
            observer = kwargs["observer"]
            observer.on_event(spawn_subagent_start(name="code_reviewer", prompt="Review"))
            (tmp_path / "review_verdict.old.json").write_text("{}\n")
            observer.on_event(spawn_subagent_result(content=json.dumps(reviewer_output)))
            assert self._result is not None
            return self._result

    outcome = await DreamBeatRunner(
        _MutatesDuringReview(result=_result("done")),
        working_dir=tmp_path,
        subagent_evidence={"code_reviewer": ("review_verdict.json", {"cleared": True})},
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.passed is False
    assert "changed the worktree during independent review" in outcome.summary


async def test_run_task_accepts_mutating_test_author_provenance(tmp_path: Path) -> None:
    author_output = {
        "authored": True,
        "files": ["tests/test_links.py"],
        "covers": ["create and resolve"],
        "red_evidence": "red-confirmed",
        "evidence": "python -m pytest -q",
    }

    class _AuthorsTestsThenProductionChanges(_FakeHarness):
        async def run_task(self, **kwargs: Any) -> _Result:
            observer = kwargs["observer"]
            observer.on_event(spawn_subagent_start(name="test_author", prompt="Author tests"))
            tests = tmp_path / "tests"
            tests.mkdir()
            (tests / "test_links.py").write_text("def test_links():\n    assert True\n")
            observer.on_event(spawn_subagent_result(content=json.dumps(author_output)))
            (tmp_path / "links.py").write_text("VALUE = 1\n")
            assert self._result is not None
            return self._result

    outcome = await DreamBeatRunner(
        _AuthorsTestsThenProductionChanges(result=_result("done")),
        working_dir=tmp_path,
        subagent_evidence={"test_author": ("test_plan.json", {"authored": True}, False)},
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.passed is True
    provenance = json.loads(
        (tmp_path / ".harness" / "subagent-evidence" / "test_author.json").read_text()
    )
    assert provenance["evidence_read_only"] is False
    assert json.loads((tmp_path / "test_plan.json").read_text()) == author_output


async def test_rebeat_keeps_validated_test_author_evidence(tmp_path: Path) -> None:
    """Live 2026-07-17: an integrate re-beat over an already-green worktree spawned test_author
    again; it honestly reported authored=false ("RED impossible: production already present") and
    clobbered test_plan.json — demoting a passing beat to failed despite beat-1's validated
    provenance. A failed re-attempt must not erase evidence a prior beat already proved."""
    requirement = {"test_author": ("test_plan.json", {"authored": True}, False)}
    authored = {
        "authored": True,
        "files": ["tests/test_links.py"],
        "covers": ["create and resolve"],
        "red_evidence": "red-confirmed",
        "evidence": "python -m pytest -q",
    }
    declined = {
        "authored": False,
        "files": ["tests/test_links.py"],
        "covers": ["create and resolve"],
        "red_evidence": "RED-first could not be satisfied: suite already green",
        "evidence": "python -m pytest -q -> 9 passed",
    }

    def _events(output: dict[str, object]) -> tuple[RunTaskEvent, ...]:
        return (
            spawn_subagent_start(name="test_author", prompt="Author tests"),
            spawn_subagent_result(content=json.dumps(output)),
        )

    first = await DreamBeatRunner(
        _FakeHarness(result=_result("done"), events=_events(authored)),
        working_dir=tmp_path,
        subagent_evidence=requirement,
    ).run_task(task_id=uid("t1"), intent="x")
    assert first.passed is True

    # The re-beat's subagent rewrites the worktree artifact itself (as the real one does)...
    (tmp_path / "test_plan.json").write_text(json.dumps(declined))
    rebeat = await DreamBeatRunner(
        _FakeHarness(result=_result("done"), events=_events(declined)),
        working_dir=tmp_path,
        subagent_evidence=requirement,
    ).run_task(task_id=uid("t1"), intent="integrate")

    assert rebeat.passed is True  # beat-1's validated provenance is the durable proof
    assert rebeat.outcome["subagent_evidence"] == "passed"


async def test_first_beat_still_fails_without_authored_evidence(tmp_path: Path) -> None:
    """The RED-first ratchet binds first-time work: no prior provenance, authored=false fails."""
    declined = {
        "authored": False,
        "files": [],
        "covers": [],
        "red_evidence": "did not author",
        "evidence": "",
    }
    events = (
        spawn_subagent_start(name="test_author", prompt="Author tests"),
        spawn_subagent_result(content=json.dumps(declined)),
    )
    outcome = await DreamBeatRunner(
        _FakeHarness(result=_result("done"), events=events),
        working_dir=tmp_path,
        subagent_evidence={"test_author": ("test_plan.json", {"authored": True}, False)},
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.passed is False
    assert "required claim" in outcome.summary


async def test_review_provenance_ignores_post_review_machine_bookkeeping(tmp_path: Path) -> None:
    reviewer_output = {"cleared": True, "findings": [], "evidence": "reviewed links.py"}
    (tmp_path / "links.py").write_text("VALUE = 1\n")
    (tmp_path / "review_verdict.json").write_text(json.dumps(reviewer_output))
    events = (
        spawn_subagent_start(name="code_reviewer", prompt="Review"),
        spawn_subagent_result(content=json.dumps(reviewer_output)),
    )

    class _WritesBookkeepingAfterReview(_FakeHarness):
        async def run_task(self, **kwargs: Any) -> _Result:
            result = await super().run_task(**kwargs)
            (tmp_path / "TODO.md").write_text("- [x] independent review\n")
            report = tmp_path / "security_scan" / "report.json"
            report.parent.mkdir()
            report.write_text('{"verdict": "clean"}\n')
            evaluation = tmp_path / "docs" / "evals" / uid("run-1") / "sprint-1.json"
            evaluation.parent.mkdir(parents=True)
            evaluation.write_text('{"outcome": "pass"}\n')
            plan = tmp_path / "docs" / "exec-plans" / "active" / "run-1.json"
            plan.parent.mkdir(parents=True)
            plan.write_text('{"status": "complete"}\n')
            evidence = tmp_path / "test_evidence" / "discovered-gate.txt"
            evidence.parent.mkdir()
            evidence.write_text("gate passed\n")
            (tmp_path / "test_plan.json").write_text('{"authored": true}\n')
            return result

    outcome = await DreamBeatRunner(
        _WritesBookkeepingAfterReview(result=_result("done"), events=events),
        working_dir=tmp_path,
        subagent_evidence={"code_reviewer": ("review_verdict.json", {"cleared": True})},
    ).run_task(task_id=uid("t1"), intent="x")

    assert outcome.passed is True


# -- the failure contract: a raise -> a typed disposition (spec 05 §5) -----------------------------


async def test_run_task_classifies_a_run_task_error_as_errored() -> None:
    harness = _FakeHarness(error=_FakeRunTaskError("planner blew up", phase="plan"))
    outcome = await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x")
    assert outcome.passed is False
    assert outcome.disposition is BeatDisposition.ERRORED
    assert outcome.outcome["phase"] == "plan"  # the typed phase rides onto the outcome
    assert "planner blew up" in str(outcome.outcome["error"])


async def test_run_task_classifies_task_cancelled_as_cancelled() -> None:
    harness = _FakeHarness(error=_FakeTaskCancelled("budget exhausted"))
    outcome = await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x")
    assert outcome.passed is False
    assert outcome.disposition is BeatDisposition.CANCELLED
    assert "budget exhausted" in str(outcome.outcome["cancelled"])


async def test_run_task_propagates_asyncio_cancellation() -> None:
    # structured cancellation must never be swallowed into a beat outcome — it re-raises.
    harness = _FakeHarness(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await DreamBeatRunner(harness).run_task(task_id=uid("t1"), intent="x")


async def test_run_task_arms_todo_flush_nudge_at_ninety_percent_budget(tmp_path: Path) -> None:
    timeout_s = 0.2
    runner = DreamBeatRunner(
        _HangingHarness(),
        timeout_s=timeout_s,
        working_dir=tmp_path,
        employee_id="bex",
    )
    run = asyncio.create_task(
        runner.run_task(task_id=uid("t1"), intent="x", run_id=uid("run-1")),
    )
    try:
        await asyncio.sleep(timeout_s * 0.91)
        nudge = read_todo_flush_nudge(tmp_path)
        assert nudge is not None
        assert nudge.timeout_s == timeout_s
        assert nudge.remaining_s == pytest.approx(timeout_s * 0.10)
    finally:
        outcome = await run
        assert outcome.disposition is BeatDisposition.ERRORED
        assert read_todo_flush_nudge(tmp_path) is None


async def test_run_task_clears_stale_todo_flush_nudge_at_beat_start(tmp_path: Path) -> None:
    from chorus.heartbeat._todo_flush import write_todo_flush_nudge

    write_todo_flush_nudge(tmp_path, timeout_s=10.0, remaining_s=1.0)
    harness = _FakeHarness(result=_result("done"))
    await DreamBeatRunner(harness, working_dir=tmp_path, employee_id="bex").run_task(
        task_id=uid("t1"), intent="x", run_id=uid("run-1")
    )
    assert read_todo_flush_nudge(tmp_path) is None


def test_beat_outcome_disposition_defaults_from_passed() -> None:
    from chorus.heartbeat import BeatOutcome

    assert BeatOutcome(passed=True).disposition is BeatDisposition.PASSED
    assert BeatOutcome(passed=False).disposition is BeatDisposition.DOD_FAILED
    assert to_beat_outcome(_result("done")).disposition is BeatDisposition.PASSED
    assert to_beat_outcome(_result("blocked")).disposition is BeatDisposition.DOD_FAILED
