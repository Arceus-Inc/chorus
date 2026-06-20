"""Observability & inspection (spec 08).

The event stream is the spine; the inspector is a pure read model over the
ledger + log. "Working vs stuck" is witnessed from typed state, not guessed from
byte-silence.
"""

from __future__ import annotations

from chorus.observability._bus import EventBus, EventSink, FanoutBus, Subscriber
from chorus.observability._inspector import Inspector, LedgerInspector
from chorus.observability._views import (
    EmployeeView,
    IncidentView,
    OrgObservabilityReport,
    RoutineRunView,
    RoutineTriggerView,
    RoutineView,
    RunView,
    ScrumChildView,
    ScrumPacketView,
    TaskView,
    WorkforceStatus,
)

__all__ = [
    "EmployeeView",
    "EventBus",
    "EventSink",
    "FanoutBus",
    "IncidentView",
    "Inspector",
    "LedgerInspector",
    "OrgObservabilityReport",
    "RoutineRunView",
    "RoutineTriggerView",
    "RoutineView",
    "RunView",
    "ScrumChildView",
    "ScrumPacketView",
    "Subscriber",
    "TaskView",
    "WorkforceStatus",
]
