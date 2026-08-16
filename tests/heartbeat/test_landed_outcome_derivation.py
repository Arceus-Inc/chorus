"""TDD: derive_landed_outcome — the scheduler's single authoritative landing phase (Phase 0)."""

from __future__ import annotations

import pytest
from dream.contracts.strategy import LandedPhase, RecoveryHint

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.heartbeat._landed_outcome import derive_landed_outcome
from chorus.ledger import ExecutionMode, Task, TaskStatus
from chorus.ledger._models._enums import DodStatus


def _task(**overrides: object) -> Task:
    defaults: dict[str, object] = {
        "id": "task-1",
        "intent": "ship it",
        "status": TaskStatus.DONE,
        "execution_mode": ExecutionMode.DELIVERY,
    }
    defaults.update(overrides)
    return Task(**defaults)  # type: ignore[arg-type]


def _result(**overrides: object) -> BeatOutcome:
    defaults: dict[str, object] = {"passed": True, "summary": "ok"}
    defaults.update(overrides)
    return BeatOutcome(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("task_kwargs", "result_kwargs", "dod_status", "orchestrated", "expected_phase", "expected_passed"),
    [
        ({}, {"passed": True}, DodStatus.PASSED, False, LandedPhase.TERMINAL_PASS, True),
        (
            {"status": TaskStatus.REJECTED},
            {"passed": False, "disposition": BeatDisposition.DOD_FAILED},
            DodStatus.FAILED,
            False,
            LandedPhase.TERMINAL_FAIL,
            False,
        ),
        (
            {"status": TaskStatus.TODO},
            {"passed": False, "disposition": BeatDisposition.DOD_FAILED, "summary": "missing tests"},
            DodStatus.FAILED,
            False,
            LandedPhase.NEEDS_REWORK,
            False,
        ),
        (
            {"status": TaskStatus.BLOCKED, "execution_mode": ExecutionMode.DELEGATION},
            {"passed": True, "disposition": BeatDisposition.PASSED},
            DodStatus.PASSED,
            True,
            LandedPhase.DELEGATED,
            None,
        ),
        (
            {"status": TaskStatus.BLOCKED},
            {
                "passed": False,
                "disposition": BeatDisposition.ERRORED,
                "outcome": {"error": "tool fault"},
            },
            None,
            False,
            LandedPhase.STRANDED,
            None,
        ),
        (
            {},
            {"passed": False, "disposition": BeatDisposition.CANCELLED},
            None,
            False,
            LandedPhase.CANCELLED,
            None,
        ),
    ],
)
def test_derive_landed_outcome_matrix(
    task_kwargs: dict[str, object],
    result_kwargs: dict[str, object],
    dod_status: DodStatus | None,
    orchestrated: bool,
    expected_phase: LandedPhase,
    expected_passed: bool | None,
) -> None:
    landed = derive_landed_outcome(
        _task(**task_kwargs),
        _result(**result_kwargs),
        dod_status,
        orchestrated=orchestrated,
    )
    assert landed.phase is expected_phase
    assert landed.strategy_passed() is expected_passed


def test_delegation_decompose_is_delegated_not_terminal_fail() -> None:
    """Regression: orchestrated hand-off must not collapse to TERMINAL_FAIL on parent DoD."""
    landed = derive_landed_outcome(
        _task(
            status=TaskStatus.BLOCKED,
            execution_mode=ExecutionMode.DELEGATION,
        ),
        _result(passed=True, disposition=BeatDisposition.PASSED),
        DodStatus.FAILED,
        orchestrated=True,
    )
    assert landed.phase is LandedPhase.DELEGATED
    assert landed.recovery_hint() is RecoveryHint.WAIT_FOR_CHILDREN


def test_needs_rework_recovery_hint() -> None:
    landed = derive_landed_outcome(
        _task(status=TaskStatus.IN_PROGRESS),
        _result(passed=False, disposition=BeatDisposition.DOD_FAILED),
        DodStatus.FAILED,
    )
    assert landed.recovery_hint() is RecoveryHint.REWORK


def test_derive_rejects_unmapped_state() -> None:
    with pytest.raises(ValueError, match="cannot derive landed outcome"):
        derive_landed_outcome(
            _task(status=TaskStatus.IN_PROGRESS),
            _result(passed=False, disposition=BeatDisposition.ERRORED),
            DodStatus.PENDING,
        )


def test_unmerged_pr_redispatch_is_needs_rework_not_terminal_pass() -> None:
    landed = derive_landed_outcome(
        _task(status=TaskStatus.TODO),
        _result(passed=True, disposition=BeatDisposition.PASSED),
        DodStatus.PENDING,
        unmerged_pr=True,
    )
    assert landed.phase is LandedPhase.NEEDS_REWORK
    assert landed.strategy_passed() is False
    assert landed.recovery_hint() is RecoveryHint.REWORK


def test_unmerged_pr_exhausted_is_stranded_not_terminal_pass() -> None:
    landed = derive_landed_outcome(
        _task(status=TaskStatus.BLOCKED),
        _result(passed=True, disposition=BeatDisposition.PASSED),
        DodStatus.PENDING,
        unmerged_pr=True,
    )
    assert landed.phase is LandedPhase.STRANDED
    assert landed.strategy_passed() is None
    assert landed.recovery_hint() is RecoveryHint.ESCALATE
