"""The Employee value object and its lifecycle enum (spec 06 §1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EmployeeStatus(StrEnum):
    """An employee's lifecycle (spec 01 Cluster D ``employee.status``)."""

    PENDING = "pending"  # hired but not yet approved (§5 hire_employee gate) — uninvokable
    IDLE = "idle"
    ACTIVE = "active"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class Employee:
    """A replayable identity, not a process (spec 06 §1).

    ``reports_to`` is the org-chart edge (no cycles; ``terminated`` is
    irreversible — spec 06 §3). Budget columns are advisory mirrors;
    ``spent_monthly_cents`` is always recomputed live from ``cost_event`` on read,
    never trusted (spec 04 §3).
    """

    id: str
    name: str
    role: str
    reports_to: str | None = None
    memory_scope: str = "project"
    status: EmployeeStatus = EmployeeStatus.IDLE
    budget_monthly_cents: int | None = None
    spent_monthly_cents: int = 0
    last_beat_at: str | None = None


__all__ = ["Employee", "EmployeeStatus"]
