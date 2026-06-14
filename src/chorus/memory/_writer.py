"""Append-only sprint memory — chorus owns the mechanism, lattice the policy (spec 07).

chorus implements dream's ``MemoryWriter`` contract with an **append-only** writer:
one raw episodic delta per beat, with provenance, and *nothing more* (B4.1). It
never consolidates — no promotion episodic→semantic, no compaction, no
forgetting; the memory git just grows. The day chorus decides *what is worth
remembering* it has rebuilt lattice inside itself, so it stops at "write raw" and
**reserves the consolidation seam** for the lattice sibling (spec 07 §4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dream.contracts import MemoryDelta, MemoryRecord


@dataclass(frozen=True)
class SprintDelta:
    """The one raw episodic record chorus writes per beat (spec 07 §3).

    Every field above the markdown ``---`` is **derived from the run, never
    authored by the worker** — ``outcome``/``score``/``artifacts`` are copied
    verbatim from the ``RunTaskResult`` (spec 05) so the record is an honest
    trace, not a self-report.
    """

    run_id: str
    task_id: str
    employee_id: str
    scope: str
    intent: str
    outcome: str
    score: float
    created_at: datetime
    kind: str = "sprint_delta"
    artifacts: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    body: str = ""


class AppendOnlyMemoryWriter:
    """The chorus ``MemoryWriter`` — write a new ``*.md``, never merge (spec 07 §3).

    One file per record named by ``run_id`` (``{scope}/{run_id}.md``): because
    each run id is unique, two concurrent beats never target the same path, so
    appends are conflict-free by construction. ``lattice``'s consolidating writer
    is the only thing that ever rewrites existing files (spec 07 §4 seam).
    """

    def __init__(self, memory_repo: str) -> None:
        self.memory_repo = memory_repo

    async def apply(self, delta: MemoryDelta) -> MemoryRecord:
        """Write a new scoped ``*.md`` and commit it; never compress/forget (spec 07 §3)."""
        raise NotImplementedError("spec 07 §3: write new file under scope dir, commit per delta")

    async def rollback(self, record_id: str, to_version: str) -> None:
        """Git-revert a record to an earlier version (spec 07 §3)."""
        raise NotImplementedError("spec 07 §3: git revert, never force")


__all__ = [
    "AppendOnlyMemoryWriter",
    "SprintDelta",
]
