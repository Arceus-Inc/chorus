"""``EpisodicStore`` — episodic-memory facade with bounded recall reads (R0 + R2)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from chorus.memory.episodic.models import SprintDelta
from chorus.memory.episodic.recall_filters import EpisodicQueryFilters
from chorus.memory.episodic.search_hit import EpisodicSearchHit
from chorus.memory.repos import EpisodicRepo

if TYPE_CHECKING:
    from chorus.ledger import Ledger


class EpisodicStore:
    """Append-only per-beat episodic capture over the company ledger (shared Postgres schema).

    The ``episodic_record`` table lives beside the ledger tables — same database, same
    ``company_id`` + FORCE RLS scoping — so the store rides the ledger's connection rather
    than owning a second one.
    """

    def __init__(self, ledger: Ledger) -> None:
        self._records = EpisodicRepo(ledger.connection)

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op."""
        self._records.append(delta)

    def get(self, run_id: str) -> SprintDelta | None:
        """The record for ``run_id``, or ``None`` if absent."""
        return self._records.get(run_id)

    def records_for(
        self,
        employee_id: str,
        *,
        limit: int | None = None,
        filters: EpisodicQueryFilters | None = None,
    ) -> list[SprintDelta]:
        """Hot-tier records for one agent, newest first — bounded when ``limit`` is set."""
        return self._records.for_employee(employee_id, limit=limit, filters=filters)

    def search(
        self,
        query: str,
        *,
        employee_id: str | None = None,
        limit: int = 5,
        filters: EpisodicQueryFilters | None = None,
    ) -> list[EpisodicSearchHit]:
        """Keyword search over intent+body, optionally scoped to one employee."""
        return self._records.search(query, employee_id=employee_id, limit=limit, filters=filters)

    def touch_recalled(self, run_ids: tuple[str, ...], *, now: datetime) -> None:
        """Mark beats as recalled (retrieval reinforcement)."""
        self._records.touch_recalled(run_ids, now=now)

    def pin_run_ids(self, employee_id: str, run_ids: tuple[str, ...]) -> None:
        """Pin cited run_ids after lattice apply."""
        self._records.pin_run_ids(employee_id, run_ids)

    def count(self) -> int:
        """Total records held."""
        return self._records.count()

    def close(self) -> None:
        """No-op — the ledger owns the connection; closing the ledger closes the store."""


__all__ = ["EpisodicStore"]
