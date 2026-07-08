"""Append-only sprint memory — chorus owns the mechanism, lattice the policy (spec 07).

chorus implements dream's ``MemoryWriter`` contract with an **append-only** writer:
one raw episodic delta per beat, with provenance, and *nothing more* (B4.1). It
never consolidates — no promotion episodic→semantic, no compaction, no
forgetting; the memory git just grows. The day chorus decides *what is worth
remembering* it has rebuilt lattice inside itself, so it stops at "write raw" and
**reserves the consolidation seam** for the lattice sibling (spec 07 §4).

The on-disk shape is dream's: one ``*.md`` per record with YAML frontmatter
(``name`` + ``metadata.{type,scope,…}``) and a free-form body, so dream's own
``MemoryStore`` reads back exactly what this writer lays down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dream.contracts import MemoryDelta, MemoryRecord, MemoryScope, MemoryType

_FENCE = "---"


@dataclass(frozen=True)
class SprintDelta:
    """The one raw episodic record chorus writes per beat (spec 07 §3).

    Every field is **derived from the run, never authored by the worker** —
    ``outcome``/``score``/``artifacts`` are copied verbatim from the
    ``RunTaskResult`` (spec 05) so the record is an honest trace, not a
    self-report.
    """

    run_id: str
    task_id: str
    employee_id: str
    scope: str
    intent: str
    outcome: str
    score: float
    created_at: datetime
    role: str = ""
    recorded_at: datetime | None = None
    kind: str = "sprint_delta"
    artifacts: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    body: str = ""

    def to_memory_delta(self) -> MemoryDelta:
        """Project the typed sprint delta onto the generic ``MemoryDelta`` contract (a ``create``).

        The provenance + verbatim run fields ride in ``metadata`` (they become the record's
        frontmatter); ``new_content`` is the free-form body.
        """
        metadata: dict[str, Any] = {
            "type": MemoryType.PROJECT.value,
            "kind": self.kind,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "employee_id": self.employee_id,
            "role": self.role,
            "scope": self.scope,
            "intent": self.intent,
            "outcome": self.outcome,
            "score": self.score,
            "artifacts": list(self.artifacts),
            "files_touched": list(self.files_touched),
            "created_at": self.created_at.isoformat(),
            "recorded_at": (self.recorded_at or self.created_at).isoformat(),
        }
        return MemoryDelta(
            target_id=self.run_id,
            scope=MemoryScope(self.scope),
            operation="create",
            new_content=self.body,
            rationale=self.intent,
            metadata=metadata,
        )


class AppendOnlyMemoryWriter:
    """The chorus ``MemoryWriter`` — write a new ``*.md``, never merge (spec 07 §3).

    One file per record named by ``run_id``, partitioned per agent (``{employee_id}/{run_id}.md``):
    episodic memory is one agent's own history, so its stream is its own subtree. Because each run id
    is unique, two concurrent beats never target the same path, so appends are conflict-free by
    construction. An existing file is **never** rewritten — a re-apply (a crash retry) is an idempotent
    no-op. ``lattice``'s consolidating writer is the only thing that ever rewrites files (the §4 seam).
    """

    def __init__(self, memory_repo: str | Path) -> None:
        self._root = Path(memory_repo)

    async def apply(self, delta: MemoryDelta) -> MemoryRecord:
        """Write a new per-agent ``*.md`` and return its record; never compress/forget (spec 07 §3)."""
        partition = str(delta.metadata.get("employee_id") or delta.scope.value)
        agent_dir = self._root / partition
        path = agent_dir / f"{delta.target_id}.md"
        if not path.exists():  # append-only: the first write for a run id wins, forever
            agent_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(_render(delta), encoding="utf-8")
        return _record_from(path, delta)

    async def rollback(self, record_id: str, to_version: str) -> MemoryRecord:
        """Remove an appended record — the only undo append-only supports (spec 07 §3).

        Versioned revert (restore an earlier body) is lattice's job; the append-only file store has a
        single version per ``run_id``, so a rollback simply drops it. Raises if the record is absent.
        """
        path = next((p for p in self._root.glob(f"*/{record_id}.md")), None)
        if path is None:
            raise FileNotFoundError(f"no memory record {record_id!r} under {self._root}")
        record = _scan_back(path)
        path.unlink()
        return record


def _render(delta: MemoryDelta) -> str:
    """Render a delta as a dream-readable record: YAML frontmatter + free-form body."""
    header = {
        "name": delta.target_id,
        "description": delta.rationale or delta.metadata.get("intent", ""),
        "metadata": delta.metadata,
    }
    front = yaml.safe_dump(header, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"{_FENCE}\n{front}\n{_FENCE}\n{delta.new_content or ''}\n"


def _record_from(path: Path, delta: MemoryDelta) -> MemoryRecord:
    """The :class:`MemoryRecord` for a just-written (or already-present) delta."""
    type_value = str(delta.metadata.get("type", MemoryType.PROJECT.value))
    return MemoryRecord(
        id=delta.target_id,
        scope=delta.scope,
        type=MemoryType(type_value),
        content=delta.new_content or "",
        source=path,
        frontmatter=dict(delta.metadata),
    )


def _scan_back(path: Path) -> MemoryRecord:
    """Parse an on-disk record back into a :class:`MemoryRecord` (for rollback's return)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == _FENCE), len(lines))
    header = yaml.safe_load("\n".join(lines[1:end])) or {}
    raw = header.get("metadata") if isinstance(header, dict) else None
    metadata: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return MemoryRecord(
        id=str(header.get("name") or path.stem),
        scope=MemoryScope(str(metadata.get("scope", MemoryScope.PROJECT.value))),
        type=MemoryType(str(metadata.get("type", MemoryType.PROJECT.value))),
        content="\n".join(lines[end + 1 :]).strip(),
        source=path,
        frontmatter=metadata,
    )


__all__ = [
    "AppendOnlyMemoryWriter",
    "SprintDelta",
]
