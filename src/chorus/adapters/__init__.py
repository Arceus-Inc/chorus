"""Adapters — the wiring boundary to external runtimes (spec 05, spec 10 §1).

Modules here adapt an external SDK to a chorus contract. They are the seam the composition root wires;
keeping them in one package makes the boundary explicit. :class:`DreamBeatRunner` runs a beat through
the dream Harness behind the :class:`~chorus.heartbeat.BeatRunner` protocol.
"""

from __future__ import annotations

from chorus.adapters._pricing import ModelRate, TokenPricing, UsageView
from chorus.adapters.dream_beat import (
    DreamBeatRunner,
    DreamStepStatus,
    RunResult,
    TaskHarness,
    to_beat_outcome,
)

__all__ = [
    "DreamBeatRunner",
    "DreamStepStatus",
    "ModelRate",
    "RunResult",
    "TaskHarness",
    "TokenPricing",
    "UsageView",
    "to_beat_outcome",
]
