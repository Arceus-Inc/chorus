"""`DeliveryIndex` — exactly one delivery per approval (design doc: idempotency).

A worktree JSON map ``approval_id → DeliveryRecord`` at ``.harness/deliveries.json``: the
reversible-write analog of the cms standing-draft index, for the *irreversible* side. A re-called
``execute_go_live`` finds the standing delivery and returns it instead of publishing twice.
Absent/malformed file degrades to an empty index — never an error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from chorus_tools.delivery._types import DeliveryRecord


@dataclass(frozen=True, slots=True)
class DeliveryIndex:
    """A worktree-persisted ``approval_id -> DeliveryRecord`` map."""

    path: Path

    def standing_delivery(self, approval_id: str) -> DeliveryRecord | None:
        """The delivery already executed for ``approval_id``, or ``None``."""
        entry = self._load().get(approval_id)
        if not isinstance(entry, dict):
            return None
        try:
            return DeliveryRecord.from_dict(entry)
        except ValueError:
            return None  # malformed entry = no standing delivery (fail open to a fresh record)

    def record(self, delivery: DeliveryRecord) -> None:
        """Persist ``delivery`` as the standing record for its approval."""
        data = self._load()
        data[delivery.approval_id] = delivery.as_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return loaded if isinstance(loaded, dict) else {}


__all__ = ["DeliveryIndex"]
