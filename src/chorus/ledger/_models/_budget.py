"""Budget row models — policies, incidents, and cost events (Cluster F)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from chorus.ledger._models._enums import (
    BudgetIncidentStatus,
    BudgetScope,
    BudgetThreshold,
)


@dataclass(frozen=True)
class BudgetPolicy:
    """A spend cap for a scope (spec 01 Cluster E, spec 04). One per scope/metric/window.

    The soft gate warns at ``warn_percent`` of ``amount``; the hard gate (when ``hard_stop_enabled``)
    blocks and opens a hard :class:`BudgetIncident` that a human approval must clear.
    """

    id: str
    scope_type: BudgetScope
    scope_id: str
    amount: int
    metric: str = "cost_cents"
    warn_percent: int = 80
    hard_stop_enabled: bool = True
    window_kind: str = "monthly"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BudgetIncident:
    """A budget breach record (spec 01 Cluster E). At most one open per policy/window/threshold.

    A hard breach attaches an :class:`Approval` (``approval_id``) — the gate a human resolves to let
    the blocked work proceed.
    """

    id: str
    policy_id: str
    threshold_type: BudgetThreshold
    amount_limit: int
    amount_observed: int
    window_start: datetime
    status: BudgetIncidentStatus = BudgetIncidentStatus.OPEN
    approval_id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class CostEvent:
    """One immutable spend record (spec 01 Cluster E ``cost_event``).

    ``spent`` is recomputed live by summing cost_events on read — never trusted as a stored counter
    (the Paperclip rule).
    """

    id: str
    employee_id: str
    provider: str
    model: str
    cost_cents: int
    task_id: str | None = None
    run_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    occurred_at: datetime | None = None
