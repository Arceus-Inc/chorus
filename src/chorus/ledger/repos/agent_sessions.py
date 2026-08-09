"""AgentSessionRepo — the handle rows pointing at dream sessions (migration 0005)."""

from __future__ import annotations

from collections.abc import Mapping

from chorus.ledger._models import (
    AgentSession,
    AgentSessionStatus,
    SessionCost,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    dumps,
    from_iso,
    loads,
    require_persisted,
    utcnow_iso,
)


def _coerce_json_dict(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = loads(value)
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(value, Mapping):
        return {str(key): val for key, val in value.items()}
    return {}


def _dump_cost(cost: SessionCost) -> str:
    return dumps(
        {
            "input_tokens": cost.input_tokens,
            "output_tokens": cost.output_tokens,
            "cache_read_tokens": cost.cache_read_tokens,
            "cache_write_tokens": cost.cache_write_tokens,
            "cost_usd": cost.cost_usd,
        }
    )


def _load_cost(value: object) -> SessionCost:
    data = _coerce_json_dict(value)
    return SessionCost(
        input_tokens=_as_int(data.get("input_tokens"), 0),
        output_tokens=_as_int(data.get("output_tokens"), 0),
        cache_read_tokens=_as_int(data.get("cache_read_tokens"), 0),
        cache_write_tokens=_as_int(data.get("cache_write_tokens"), 0),
        cost_usd=_as_float(data.get("cost_usd"), 0.0),
    )


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    return default


class AgentSessionRepo:
    """Open, look up, meter, and seal the ``agent_session`` handle rows."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def open(self, session: AgentSession) -> AgentSession:
        """Insert an open session; the partial unique index enforces one open session per task."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO agent_session (id, dream_session_key, employee_id, task_id, run_id, "
            "model, working_dir, last_error, status, cost, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.dream_session_key,
                session.employee_id,
                session.task_id,
                session.run_id,
                session.model,
                session.working_dir,
                session.last_error,
                AgentSessionStatus.OPEN.value,
                _dump_cost(session.cost),
                now,
                now,
            ),
        )
        self._conn.commit()
        opened = require_persisted(self.get(session.id), session.id)
        return opened

    def get(self, session_id: str) -> AgentSession | None:
        row = self._conn.execute(
            "SELECT * FROM agent_session WHERE id = ?", (session_id,)
        ).fetchone()
        return _row_to_session(row) if row is not None else None

    def get_open_for_task(self, task_id: str) -> AgentSession | None:
        row = self._conn.execute(
            "SELECT * FROM agent_session WHERE task_id = ? AND status = 'open' LIMIT 1",
            (task_id,),
        ).fetchone()
        return _row_to_session(row) if row is not None else None

    def latest_for_task(self, task_id: str) -> AgentSession | None:
        """Most recently updated session for the task (open or sealed)."""
        row = self._conn.execute(
            "SELECT * FROM agent_session WHERE task_id = ? ORDER BY updated_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return _row_to_session(row) if row is not None else None

    def get_by_dream_key(self, dream_session_key: str) -> AgentSession | None:
        row = self._conn.execute(
            "SELECT * FROM agent_session WHERE dream_session_key = ?",
            (dream_session_key,),
        ).fetchone()
        return _row_to_session(row) if row is not None else None

    def touch_cost(
        self,
        session_id: str,
        cost: SessionCost,
        *,
        run_id: str | None = None,
    ) -> None:
        now = utcnow_iso()
        if run_id is None:
            self._conn.execute(
                "UPDATE agent_session SET cost = ?, updated_at = ? WHERE id = ?",
                (_dump_cost(cost), now, session_id),
            )
        else:
            self._conn.execute(
                "UPDATE agent_session SET cost = ?, run_id = ?, updated_at = ? WHERE id = ?",
                (_dump_cost(cost), run_id, now, session_id),
            )
        self._conn.commit()

    def seal(self, session_id: str) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE agent_session SET status = ?, updated_at = ? WHERE id = ?",
            (AgentSessionStatus.SEALED.value, now, session_id),
        )
        self._conn.commit()

    def abort(self, session_id: str) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE agent_session SET status = ?, updated_at = ? WHERE id = ?",
            (AgentSessionStatus.ABORTED.value, now, session_id),
        )
        self._conn.commit()

    def bind_working_dir(self, session_id: str, working_dir: str) -> None:
        """Record where the thread works, the first time a beat runs it somewhere."""
        self._conn.execute(
            "UPDATE agent_session SET working_dir = ?, updated_at = ? WHERE id = ?",
            (working_dir, utcnow_iso(), session_id),
        )
        self._conn.commit()

    def record_error(self, session_id: str, last_error: str | None) -> None:
        """Set or clear why this thread last failed to resume."""
        self._conn.execute(
            "UPDATE agent_session SET last_error = ?, updated_at = ? WHERE id = ?",
            (last_error, utcnow_iso(), session_id),
        )
        self._conn.commit()


def _row_to_session(row: LedgerRow) -> AgentSession:
    return AgentSession(
        id=row["id"],
        dream_session_key=row["dream_session_key"],
        employee_id=row["employee_id"],
        task_id=row["task_id"],
        run_id=row["run_id"],
        model=row["model"],
        working_dir=row["working_dir"],
        last_error=row["last_error"],
        status=AgentSessionStatus(row["status"]),
        cost=_load_cost(row["cost"]),
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
    )
