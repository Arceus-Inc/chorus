"""Episodic models (spec 07). Mirrors ``chorus.ledger._models``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SprintDelta:
    """The one raw episodic record chorus writes per beat (spec 07 §3).

    Every field is **derived from the run, never authored by the worker** — ``outcome``/``score``/
    ``artifacts``/``files_touched`` are copied verbatim from the run so the record is an honest trace,
    not a self-report; ``body`` is the entire raw agent account (reasoning + actions).
    """

    run_id: str
    task_id: str
    employee_id: str
    scope: str
    intent: str
    outcome: str
    score: float
    created_at: datetime
    role: str = ""
    recorded_at: datetime | None = None
    kind: str = "sprint_delta"
    artifacts: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    body: str = ""
    pin_count: int = 0
    last_recalled_at: datetime | None = None
    tier: str = "hot"


__all__ = ["SprintDelta"]
