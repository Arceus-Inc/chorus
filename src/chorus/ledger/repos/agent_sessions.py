"""AgentSessionRepo — durable dream conversation + tool-call history (migration 0005)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from chorus.ledger._models import (
    AgentSession,
    AgentSessionStatus,
    ConversationMessage,
    ConversationRole,
    SessionCost,
    ToolCall,
)
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    dumps,
    from_iso,
    loads,
    require_persisted,
    to_iso,
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


def _dump_content(content: tuple[Mapping[str, object], ...]) -> str:
    return dumps([dict(block) for block in content])


def _load_content(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parsed = loads(value)
    elif isinstance(value, list):
        parsed = value
    else:
        return ()
    blocks: list[Mapping[str, object]] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, (Mapping, dict)):
                blocks.append(item)
    return tuple(blocks)


class AgentSessionRepo:
    """Open, resume, append, and seal ``agent_session`` rows and their transcript."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def open(self, session: AgentSession) -> AgentSession:
        """Insert an open session; the partial unique index enforces one open session per task."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO agent_session (id, dream_session_key, employee_id, task_id, run_id, "
            "model, system_prompt, status, cost, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.dream_session_key,
                session.employee_id,
                session.task_id,
                session.run_id,
                session.model,
                session.system_prompt,
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

    def append_messages(self, messages: Sequence[ConversationMessage]) -> None:
        """Batch-insert transcript rows; caller may wrap in ``ledger.transaction``."""
        if not messages:
            return
        now = utcnow_iso()
        for message in messages:
            self._conn.execute(
                "INSERT INTO conversation_message (id, session_id, seq, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message.id,
                    message.session_id,
                    message.seq,
                    message.role.value,
                    _dump_content(message.content),
                    now,
                ),
            )
        self._conn.commit()

    def messages_after(
        self,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[ConversationMessage]:
        rows = self._conn.execute(
            "SELECT * FROM conversation_message WHERE session_id = ? AND seq > ? "
            "ORDER BY seq LIMIT ?",
            (session_id, after_seq, limit),
        ).fetchall()
        return [_row_to_message(row) for row in rows]

    def all_messages(self, session_id: str) -> list[ConversationMessage]:
        rows = self._conn.execute(
            "SELECT * FROM conversation_message WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
        return [_row_to_message(row) for row in rows]

    def last_message_seq(self, session_id: str) -> int:
        """Highest transcript seq for the session, or ``0`` when empty (cursor seed)."""
        row = self._conn.execute(
            "SELECT seq FROM conversation_message WHERE session_id = ? "
            "ORDER BY seq DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return 0
        return int(row["seq"])

    def record_tool_call(self, call: ToolCall) -> ToolCall:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO tool_call (id, session_id, tool_use_id, tool_name, input, "
            "result_content, is_error, created_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                call.id,
                call.session_id,
                call.tool_use_id,
                call.tool_name,
                dumps(dict(call.input)),
                call.result_content,
                call.is_error,
                now,
                to_iso(call.completed_at),
            ),
        )
        self._conn.commit()
        recorded = require_persisted(self._get_tool_call(call.id), call.id)
        return recorded

    def complete_tool_call(
        self,
        session_id: str,
        tool_use_id: str,
        *,
        result_content: str,
        is_error: bool,
    ) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE tool_call SET result_content = ?, is_error = ?, completed_at = ? "
            "WHERE session_id = ? AND tool_use_id = ?",
            (result_content, is_error, now, session_id, tool_use_id),
        )
        self._conn.commit()

    def tool_calls_for(self, session_id: str) -> list[ToolCall]:
        rows = self._conn.execute(
            "SELECT * FROM tool_call WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [_row_to_tool_call(row) for row in rows]

    def _get_tool_call(self, call_id: str) -> ToolCall | None:
        row = self._conn.execute("SELECT * FROM tool_call WHERE id = ?", (call_id,)).fetchone()
        return _row_to_tool_call(row) if row is not None else None


def _row_to_session(row: LedgerRow) -> AgentSession:
    return AgentSession(
        id=row["id"],
        dream_session_key=row["dream_session_key"],
        employee_id=row["employee_id"],
        task_id=row["task_id"],
        run_id=row["run_id"],
        model=row["model"],
        system_prompt=row["system_prompt"],
        status=AgentSessionStatus(row["status"]),
        cost=_load_cost(row["cost"]),
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
    )


def _row_to_message(row: LedgerRow) -> ConversationMessage:
    return ConversationMessage(
        id=row["id"],
        session_id=row["session_id"],
        seq=int(row["seq"]),
        role=ConversationRole(row["role"]),
        content=_load_content(row["content"]),
        created_at=from_iso(row["created_at"]),
    )


def _row_to_tool_call(row: LedgerRow) -> ToolCall:
    return ToolCall(
        id=row["id"],
        session_id=row["session_id"],
        tool_use_id=row["tool_use_id"],
        tool_name=row["tool_name"],
        input=_coerce_json_dict(row["input"]),
        result_content=row["result_content"],
        is_error=row["is_error"],
        created_at=from_iso(row["created_at"]),
        completed_at=from_iso(row["completed_at"]),
    )
