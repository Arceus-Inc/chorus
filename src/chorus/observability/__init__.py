"""Observability & inspection (spec 08).

The event stream is the spine; the inspector is a pure read model over the
ledger + log. "Working vs stuck" is witnessed from typed state, not guessed from
byte-silence.
"""

from __future__ import annotations

from chorus.observability._bus import EventBus, Subscriber
from chorus.observability._inspector import Inspector, LedgerInspector
from chorus.observability._views import (
    EmployeeView,
    IncidentView,
    RunView,
    TaskView,
    WorkforceStatus,
)

__all__ = [
    "EmployeeView",
    "EventBus",
    "IncidentView",
    "Inspector",
    "LedgerInspector",
    "RunView",
    "Subscriber",
    "TaskView",
    "WorkforceStatus",
]
