"""Derive the typed landed outcome once at the scheduler choke point (Phase 0).

Bridge and horizon must not re-interpret disposition strings or DoD rows — they project
:class:`dream.contracts.strategy.LandedOutcome` mechanically from the chorus event bus.
"""

from __future__ import annotations

from dream.contracts.strategy import LandedOutcome, LandedPhase

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger._models._enums import DodStatus, TaskStatus
from chorus.ledger._models._work import Task


def derive_landed_outcome(
    task: Task,
    result: BeatOutcome,
    dod_status: DodStatus | None,
    *,
    orchestrated: bool = False,
    unmerged_pr: bool = False,
) -> LandedOutcome:
    """Map the beat's landed state to a single :class:`LandedOutcome`.

    Evaluation order is load-bearing — orchestrated delegation wins over a downstream DoD failure
    on the same beat, and ``CANCELLED`` is terminal regardless of task status. An explicit unmerged
    PR is never ``TERMINAL_PASS``: rebase is ``NEEDS_REWORK``, exhausted merge repair is ``STRANDED``.
    """
    disposition = result.disposition or (
        BeatDisposition.PASSED if result.passed else BeatDisposition.DOD_FAILED
    )
    diagnostic = _diagnostic(result)
    execution_mode = task.execution_mode.value

    if disposition is BeatDisposition.CANCELLED:
        return LandedOutcome(
            phase=LandedPhase.CANCELLED,
            summary="Beat cancelled",
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if orchestrated:
        return LandedOutcome(
            phase=LandedPhase.DELEGATED,
            summary="Delegated to subtree",
            dod_status=dod_status.value if dod_status is not None else None,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if unmerged_pr:
        if task.status is TaskStatus.BLOCKED:
            return LandedOutcome(
                phase=LandedPhase.STRANDED,
                summary="Merge conflict exhausted",
                dod_status=dod_status.value if dod_status is not None else None,
                disposition=disposition.value,
                diagnostic=diagnostic,
                execution_mode=execution_mode,
            )
        return LandedOutcome(
            phase=LandedPhase.NEEDS_REWORK,
            summary="PR did not merge — rebase",
            dod_status=dod_status.value if dod_status is not None else None,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.PASSED:
        return LandedOutcome(
            phase=LandedPhase.TERMINAL_PASS,
            summary="DoD passed",
            dod_status=dod_status.value,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.FAILED and task.status is TaskStatus.REJECTED:
        return LandedOutcome(
            phase=LandedPhase.TERMINAL_FAIL,
            summary="Deliverable rejected",
            dod_status=dod_status.value,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.FAILED and disposition is BeatDisposition.DOD_FAILED:
        return LandedOutcome(
            phase=LandedPhase.NEEDS_REWORK,
            summary="DoD failed — rework",
            dod_status=dod_status.value,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if disposition is BeatDisposition.ERRORED and task.status is TaskStatus.BLOCKED:
        return LandedOutcome(
            phase=LandedPhase.STRANDED,
            summary="Beat stranded",
            dod_status=dod_status.value if dod_status is not None else None,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.FAILED and task.status is TaskStatus.BLOCKED:
        return LandedOutcome(
            phase=LandedPhase.NEEDS_REWORK,
            summary="Blocked on failed DoD",
            dod_status=dod_status.value,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    raise ValueError(
        "cannot derive landed outcome from "
        f"disposition={disposition.value!r}, dod_status={dod_status!r}, "
        f"task.status={task.status.value!r}, orchestrated={orchestrated}"
    )


def _diagnostic(result: BeatOutcome) -> str:
    """Plain diagnostic text for Phase 0 — structured fields live on ``LandedOutcome``."""
    if result.summary:
        return result.summary
    message = result.outcome.get("message")
    if isinstance(message, str) and message:
        return message
    error = result.outcome.get("error")
    if isinstance(error, str) and error:
        return error
    return ""


__all__ = ["derive_landed_outcome"]
