"""The heartbeat — the kernel tick, the wake model, and the beat (spec 03).

Two heartbeats, named apart: a **tick** is the kernel's pulse (one pass over the
ledger); a **beat** is one employee's short ``dream.run_task`` invocation.
"""

from __future__ import annotations

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome, BeatRunner
from chorus.heartbeat._runner_for import BeatRunnerFor, single
from chorus.heartbeat._scheduler import PRIORITY_RANK, Scheduler
from chorus.heartbeat._wake import TickReport, Wake, WakeReason, WakeStatus

__all__ = [
    "PRIORITY_RANK",
    "BeatDisposition",
    "BeatOutcome",
    "BeatRunner",
    "BeatRunnerFor",
    "Scheduler",
    "TickReport",
    "Wake",
    "WakeReason",
    "WakeStatus",
    "single",
]
