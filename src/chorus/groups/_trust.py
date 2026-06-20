"""``org.trust`` — a task's trust posture (spec 14 §5.3, spec 04 §4).

Set the preset (``standard`` | ``low_trust_review``) and the boundary (the secret-ref allow-list) on a
task; the kernel resolves it at materialize (employee ∩ task ∩ run, narrower wins, fail-closed).
"""

from __future__ import annotations

from collections.abc import Mapping

from chorus.ledger import SqliteLedger
from chorus.trust import TrustPreset


class TrustFacade:
    """The ``org.trust`` surface — set a task's preset + boundary."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def set_task(
        self, task_id: str, *, preset: TrustPreset, boundary: Mapping[str, object] | None = None
    ) -> None:
        """Set ``task_id``'s trust preset + boundary (the columns already persist via ``submit``)."""
        self._ledger.tasks.set_trust(
            task_id, preset.value, dict(boundary) if boundary is not None else None
        )


__all__ = ["TrustFacade"]
