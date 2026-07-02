"""`CmsDraftIndex` — the standing-draft bookkeeping for cms_draft idempotency (design: idempotency).

A tiny JSON map in the worktree, ``key -> DraftRef``, so a cms_draft re-called within the same task
updates the standing draft rather than creating a duplicate (the reversible-write analog of
``stage_go_live``'s standing-gate). The key is ``"{content_type}:{task_id}"``. Absent/malformed file
is treated as an empty index — idempotency degrades to plain create, never an error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from chorus_tools.cms._types import DraftRef


@dataclass(frozen=True, slots=True)
class CmsDraftIndex:
    """A worktree-persisted ``key -> DraftRef`` map for standing drafts."""

    path: Path

    def standing_ref(self, key: str) -> DraftRef | None:
        """The ref last staged under ``key``, or ``None`` if there is none."""
        entry = self._load().get(key)
        return DraftRef.from_dict(entry) if isinstance(entry, dict) else None

    def record(self, key: str, ref: DraftRef) -> None:
        """Persist ``ref`` as the standing draft for ``key`` (overwriting any prior)."""
        data = self._load()
        data[key] = ref.as_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return loaded if isinstance(loaded, dict) else {}


__all__ = ["CmsDraftIndex"]
