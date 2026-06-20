"""Locate and open the durable spines of one experiment run (spec 08 §1).

A run leaves three readable traces on disk:

- the **ledger** (``ledger.db``) — the durable DAG of tasks/runs/artifacts/cost (spec 01);
- the **event log** (``events.jsonl``) — dream's witnessed ``run.*`` stream + chorus's org events;
- the **memory store** (``memory/{scope}/{run_id}.md``) — one append-only episodic delta per beat (spec 07).

The ledger path is given; the other two are discovered next to it (``build_beat_service`` writes both
under ``{work_root}/{company}/``). All three are optional to *read* — the platform degrades to whatever
is present.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chorus.ledger import SqliteLedger


@dataclass(frozen=True)
class ExperimentSources:
    """The opened ledger plus the located (maybe-absent) event log and memory store for one run."""

    ledger: SqliteLedger
    db_path: Path
    events_path: Path | None
    memory_dir: Path | None

    @classmethod
    def discover(
        cls,
        db_path: str | Path,
        *,
        events_path: str | Path | None = None,
        memory_dir: str | Path | None = None,
        search_root: str | Path | None = None,
    ) -> ExperimentSources:
        """Open the ledger at ``db_path`` and find its sibling event log + memory store.

        ``events_path`` / ``memory_dir`` pin a location explicitly; otherwise both are searched for
        under ``search_root`` (default: the ledger's own directory tree).
        """
        db = Path(db_path).expanduser().resolve()
        if not db.is_file():
            raise FileNotFoundError(f"no ledger at {db}")
        root = Path(search_root).expanduser().resolve() if search_root is not None else db.parent

        events = Path(events_path).expanduser().resolve() if events_path else _find_events(root)
        memory = (
            Path(memory_dir).expanduser().resolve()
            if memory_dir
            else _find_memory(root, near=events)
        )
        return cls(
            ledger=SqliteLedger.open(str(db)),
            db_path=db,
            events_path=events if events and events.is_file() else None,
            memory_dir=memory if memory and memory.is_dir() else None,
        )

    def close(self) -> None:
        """Release the ledger connection."""
        self.ledger.close()

    def __enter__(self) -> ExperimentSources:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _find_events(root: Path) -> Path | None:
    """The newest ``events.jsonl`` at/under ``root`` (the canonical company-root spine)."""
    direct = root / "events.jsonl"
    if direct.is_file():
        return direct
    candidates = sorted(root.rglob("events.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _find_memory(root: Path, *, near: Path | None) -> Path | None:
    """The memory store — preferentially the ``memory/`` beside the event log, else a search."""
    if near is not None and (near.parent / "memory").is_dir():
        return near.parent / "memory"
    candidates = [
        path
        for path in root.rglob("memory")
        if path.is_dir() and any(path.glob("*/*.md"))
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


__all__ = ["ExperimentSources"]
