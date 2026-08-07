"""Observability & inspection (spec 08).

The event stream is the spine; the inspector is a pure read model over the
ledger + log. "Working vs stuck" is witnessed from typed state, not guessed from
byte-silence.
"""

from __future__ import annotations

from chorus.observability._bus import EventBus, EventSink, FanoutBus, Subscriber
from chorus.observability._inspector import Inspector, LedgerInspector
from chorus.observability._otel import otel_sink_if_configured, with_otel_export
from chorus.observability._otel_config import OtelConfig, is_otel_enabled, load_otel_config
from chorus.observability._views import (
    DelegationContractView,
    EmployeeView,
    IncidentView,
    ManagementProfileView,
    OrgObservabilityReport,
    RoutineRunView,
    RoutineTriggerView,
    RoutineView,
    RunView,
    ScrumChildView,
    ScrumPacketView,
    TaskView,
    TeamView,
    WorkforceStatus,
)

__all__ = [
    "DelegationContractView",
    "EmployeeView",
    "EventBus",
    "EventSink",
    "FanoutBus",
    "IncidentView",
    "Inspector",
    "LedgerInspector",
    "ManagementProfileView",
    "OrgObservabilityReport",
    "OtelConfig",
    "RoutineRunView",
    "RoutineTriggerView",
    "RoutineView",
    "RunView",
    "ScrumChildView",
    "ScrumPacketView",
    "Subscriber",
    "TaskView",
    "TeamView",
    "WorkforceStatus",
    "is_otel_enabled",
    "load_otel_config",
    "otel_sink_if_configured",
    "with_otel_export",
]
