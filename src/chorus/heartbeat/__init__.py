"""The heartbeat — the kernel tick, the wake model, and the beat (spec 03).

Two heartbeats, named apart: a **tick** is the kernel's pulse (one pass over the
ledger); a **beat** is one employee's short ``dream.run_task`` invocation.
"""

from __future__ import annotations

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome, BeatRunner, SessionScopeFactory
from chorus.heartbeat._beat_context import (
    BeatContext,
    ChildOutcomeContext,
    IntegrateContextPacket,
    ReportContext,
)
from chorus.heartbeat._execution_profile import (
    DELEGATION_BRIEF,
    ExecutionProfileDenied,
    ExecutionProfileResolver,
    ResolvedExecutionProfile,
)
from chorus.heartbeat._runner_for import BeatRunnerFor, BeatRunnerForFn, runner_from, single
from chorus.heartbeat._scheduler import PRIORITY_RANK, Scheduler
from chorus.heartbeat._wake import TickReport, Wake, WakeReason, WakeStatus

__all__ = [
    "DELEGATION_BRIEF",
    "PRIORITY_RANK",
    "BeatContext",
    "BeatDisposition",
    "BeatOutcome",
    "BeatRunner",
    "BeatRunnerFor",
    "BeatRunnerForFn",
    "ChildOutcomeContext",
    "ExecutionProfileDenied",
    "ExecutionProfileResolver",
    "IntegrateContextPacket",
    "ReportContext",
    "ResolvedExecutionProfile",
    "Scheduler",
    "SessionScopeFactory",
    "TickReport",
    "Wake",
    "WakeReason",
    "WakeStatus",
    "runner_from",
    "single",
]
