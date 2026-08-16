"""Derive the typed landed outcome once at the scheduler choke point (Phase 0).

Bridge and horizon must not re-interpret disposition strings or DoD rows — they project
:class:`dream.contracts.strategy.LandedOutcome` mechanically from the chorus event bus.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from dream.contracts.strategy import LandedOutcome, LandedPhase, RecoveryHint

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import IntegrationVerdict
from chorus.ledger._models._enums import DodStatus, TaskStatus
from chorus.ledger._models._work import Task

_EMPTY_INTEGRATION = IntegrationVerdict()


@dataclass(frozen=True)
class DerivedLandedOutcome:
    """Chorus's event-ready landed outcome plus authoritative integration truth."""

    strategy: LandedOutcome
    integration: IntegrationVerdict = _EMPTY_INTEGRATION

    @property
    def phase(self) -> LandedPhase:
        return self.strategy.phase

    def strategy_passed(self) -> bool | None:
        return self.strategy.strategy_passed()

    def recovery_hint(self) -> RecoveryHint:
        return self.strategy.recovery_hint()

    def to_dict(self) -> dict[str, object]:
        return {**self.strategy.to_dict(), **self.integration.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DerivedLandedOutcome:
        """Rehydrate the durable landed receipt without weakening integration types."""
        integration_ok = data.get("integration_ok")
        if integration_ok is not None and type(integration_ok) is not bool:
            raise ValueError("integration_ok must be a boolean or null")
        integration_note = data.get("integration_note")
        if integration_note is not None and not isinstance(integration_note, str):
            raise ValueError("integration_note must be a string or null")
        return cls(
            strategy=LandedOutcome.from_dict(data),
            integration=IntegrationVerdict(ok=integration_ok, note=integration_note),
        )


def derive_landed_outcome(
    task: Task,
    result: BeatOutcome,
    dod_status: DodStatus | None,
    *,
    orchestrated: bool = False,
    unmerged_pr: bool = False,
    integration: IntegrationVerdict = _EMPTY_INTEGRATION,
) -> DerivedLandedOutcome:
    """Map the beat's landed state and integration truth to one typed event value.

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
        return _derived(
            integration,
            phase=LandedPhase.CANCELLED,
            summary="Beat cancelled",
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if orchestrated:
        return _derived(
            integration,
            phase=LandedPhase.DELEGATED,
            summary="Delegated to subtree",
            dod_status=dod_status.value if dod_status is not None else None,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if unmerged_pr:
        if task.status is TaskStatus.BLOCKED:
            return _derived(
                integration,
                phase=LandedPhase.STRANDED,
                summary="Merge conflict exhausted",
                dod_status=dod_status.value if dod_status is not None else None,
                disposition=disposition.value,
                diagnostic=diagnostic,
                execution_mode=execution_mode,
            )
        return _derived(
            integration,
            phase=LandedPhase.NEEDS_REWORK,
            summary="PR did not merge — rebase",
            dod_status=dod_status.value if dod_status is not None else None,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.PASSED:
        return _derived(
            integration,
            phase=LandedPhase.TERMINAL_PASS,
            summary="DoD passed",
            dod_status=dod_status.value,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.FAILED and task.status is TaskStatus.REJECTED:
        return _derived(
            integration,
            phase=LandedPhase.TERMINAL_FAIL,
            summary="Deliverable rejected",
            dod_status=dod_status.value,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.FAILED and disposition is BeatDisposition.DOD_FAILED:
        return _derived(
            integration,
            phase=LandedPhase.NEEDS_REWORK,
            summary="DoD failed — rework",
            dod_status=dod_status.value,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if disposition is BeatDisposition.ERRORED and task.status is TaskStatus.BLOCKED:
        return _derived(
            integration,
            phase=LandedPhase.STRANDED,
            summary="Beat stranded",
            dod_status=dod_status.value if dod_status is not None else None,
            disposition=disposition.value,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        )

    if dod_status is DodStatus.FAILED and task.status is TaskStatus.BLOCKED:
        return _derived(
            integration,
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


def _derived(
    integration: IntegrationVerdict,
    *,
    phase: LandedPhase,
    summary: str,
    dod_status: str | None = None,
    disposition: str | None = None,
    diagnostic: str = "",
    execution_mode: str | None = None,
) -> DerivedLandedOutcome:
    return DerivedLandedOutcome(
        strategy=LandedOutcome(
            phase=phase,
            summary=summary,
            dod_status=dod_status,
            disposition=disposition,
            diagnostic=diagnostic,
            execution_mode=execution_mode,
        ),
        integration=integration,
    )


__all__ = ["DerivedLandedOutcome", "derive_landed_outcome"]
