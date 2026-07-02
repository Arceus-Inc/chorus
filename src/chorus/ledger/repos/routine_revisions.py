"""RoutineRevisionRepo — a routine's immutable definition history (spec 01 Cluster C ``routine_revision``).

Append-only: ``append`` writes one version, the ``(routine_id, revision_no)`` unique index forbids a
duplicate number, and ``head`` is the highest-numbered (live) revision. A routine's live row points at
the head via ``routine.latest_revision_id``; a ``routine_run`` pins the revision it fired under so an
edit never re-judges a firing in flight.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import (
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRevision,
    RoutineTarget,
)
from chorus.ledger.repos._base import dumps, from_iso, loads, require_persisted, utcnow_iso


class RoutineRevisionRepo:
    """Append + read ``routine_revision`` rows (never update — history is immutable)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, revision: RoutineRevision) -> RoutineRevision:
        """Write one immutable revision; the unique index rejects a duplicate ``revision_no``."""
        self._conn.execute(
            "INSERT INTO routine_revision (id, routine_id, revision_no, intent_template, target, "
            "concurrency_policy, catch_up_policy, env, change_summary, restored_from_revision_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                revision.id,
                revision.routine_id,
                revision.revision_no,
                revision.intent_template,
                revision.target.value,
                revision.concurrency_policy.value,
                revision.catch_up_policy.value,
                dumps(revision.env) if revision.env is not None else None,
                revision.change_summary,
                revision.restored_from_revision_id,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        appended = require_persisted(self.get(revision.id), revision.id)
        return appended

    def get(self, revision_id: str) -> RoutineRevision | None:
        row = self._conn.execute(
            "SELECT * FROM routine_revision WHERE id = ?", (revision_id,)
        ).fetchone()
        return _row_to_revision(row) if row is not None else None

    def get_by_no(self, routine_id: str, revision_no: int) -> RoutineRevision | None:
        row = self._conn.execute(
            "SELECT * FROM routine_revision WHERE routine_id = ? AND revision_no = ?",
            (routine_id, revision_no),
        ).fetchone()
        return _row_to_revision(row) if row is not None else None

    def by_routine(self, routine_id: str) -> list[RoutineRevision]:
        """A routine's full history, oldest revision first."""
        rows = self._conn.execute(
            "SELECT * FROM routine_revision WHERE routine_id = ? ORDER BY revision_no",
            (routine_id,),
        ).fetchall()
        return [_row_to_revision(row) for row in rows]

    def head(self, routine_id: str) -> RoutineRevision | None:
        """The live (highest-numbered) revision, or ``None`` if the routine has no revisions yet."""
        row = self._conn.execute(
            "SELECT * FROM routine_revision WHERE routine_id = ? ORDER BY revision_no DESC LIMIT 1",
            (routine_id,),
        ).fetchone()
        return _row_to_revision(row) if row is not None else None


def _row_to_revision(row: sqlite3.Row) -> RoutineRevision:
    return RoutineRevision(
        id=row["id"],
        routine_id=row["routine_id"],
        revision_no=row["revision_no"],
        intent_template=row["intent_template"],
        target=RoutineTarget(row["target"]),
        concurrency_policy=RoutineConcurrency(row["concurrency_policy"]),
        catch_up_policy=RoutineCatchUp(row["catch_up_policy"]),
        env=loads(row["env"]),
        change_summary=row["change_summary"],
        restored_from_revision_id=row["restored_from_revision_id"],
        created_at=from_iso(row["created_at"]),
    )
