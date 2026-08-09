"""Durable, typed facts carried from one task beat to the next."""

from __future__ import annotations

from dataclasses import dataclass

from dream.contracts.strategy import LandedPhase, RecoveryHint


@dataclass(frozen=True)
class RunCarryover:
    """The scheduler's reassignment-safe record of one landed beat.

    Task membership is intentionally owned by the referenced run, never copied here.
    """

    run_id: str
    phase: LandedPhase
    recovery_hint: RecoveryHint
    evaluator_notes: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    todo_digest: str = ""
    summary: str = ""


__all__ = ["RunCarryover"]
