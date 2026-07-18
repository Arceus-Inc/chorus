"""MessageRepo — the durable mailbox (spec 01 Cluster G ``message``, spec 03 §2).

A message lands here and carries no execution of its own — the scheduler turns a delivery into a
``wake(reason='message')`` for the recipient. Sender is an employee XOR a human (DB CHECK
``message_single_sender``). The inbox is a recipient's unread messages, oldest first, served off the
``message_inbox_idx`` covering index.
"""

from __future__ import annotations

from chorus.ledger._models import Message, MessageKind
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class MessageRepo:
    """Send, read, and drain ``message`` rows."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def send(self, message: Message) -> Message:
        """Persist a message; the single-sender XOR is enforced in the DB."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO message (id, from_employee_id, from_user_id, to_employee_id, task_id, "
            "body, kind, read_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (
                message.id,
                message.from_employee_id,
                message.from_user_id,
                message.to_employee_id,
                message.task_id,
                message.body,
                message.kind.value,
                now,
            ),
        )
        self._conn.commit()
        sent = require_persisted(self.get(message.id), message.id)
        return sent

    def get(self, message_id: str) -> Message | None:
        row = self._conn.execute("SELECT * FROM message WHERE id = ?", (message_id,)).fetchone()
        return _row_to_message(row) if row is not None else None

    def inbox(self, employee_id: str) -> list[Message]:
        """A recipient's unread messages, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM message WHERE to_employee_id = ? AND read_at IS NULL "
            "ORDER BY created_at, id",
            (employee_id,),
        ).fetchall()
        return [_row_to_message(row) for row in rows]

    def mark_read(self, message_id: str) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE message SET read_at = ? WHERE id = ? AND read_at IS NULL", (now, message_id)
        )
        self._conn.commit()


def _row_to_message(row: LedgerRow) -> Message:
    return Message(
        id=row["id"],
        to_employee_id=row["to_employee_id"],
        body=row["body"],
        kind=MessageKind(row["kind"]),
        from_employee_id=row["from_employee_id"],
        from_user_id=row["from_user_id"],
        task_id=row["task_id"],
        read_at=from_iso(row["read_at"]),
        created_at=from_iso(row["created_at"]),
    )
