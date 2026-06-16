"""Wake producers for assignment + messaging (spec 03 §2, spec 01 Cluster G).

Two coordination actions, each folding a durable write together with the wake that lets the *next*
beat pick it up — the async handoff between employees:

- :func:`assign_task` — set the owner (``backlog`` → ``todo``), wake them (``task_assigned``), and
  audit the handoff (``ASSIGNED``);
- :func:`deliver_message` — persist the mailbox row and wake the recipient (``message``), coalesced
  to a single "check your mail" nudge per recipient.

Both run in one ``ledger.transaction()`` so the write and its wake commit together or not at all.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from chorus.ledger._models import ActivityVerb, Wake, WakeReason
from chorus.lifecycle._audit import record_activity

if TYPE_CHECKING:
    from chorus.ledger import Message, SqliteLedger


def assign_task(
    ledger: SqliteLedger, task_id: str, employee_id: str, *, assigned_by: str | None = None
) -> Wake | None:
    """Assign ``task_id`` to ``employee_id`` and wake them (spec 03 §2).

    Atomic: the assignment, the ``task_assigned`` wake, and the ``ASSIGNED`` audit row commit
    together. Returns the enqueued wake, or ``None`` if the task is unknown or already terminal.
    """
    with ledger.transaction():
        if not ledger.tasks.assign(task_id, employee_id):
            return None
        wake = ledger.wakes.enqueue(
            Wake(
                id=f"wake_{uuid.uuid4().hex[:12]}",
                employee_id=employee_id,
                reason=WakeReason.TASK_ASSIGNED,
                payload={"task_id": task_id},
            )
        )
        record_activity(
            ledger,
            verb=ActivityVerb.ASSIGNED,
            subject_id=task_id,
            actor_employee_id=assigned_by,
            payload={"assignee": employee_id},
        )
    return wake


def deliver_message(ledger: SqliteLedger, message: Message) -> Wake:
    """Persist ``message`` and wake its recipient (spec 03 §2, spec 01 Cluster G).

    Atomic: the mailbox row and the ``message`` wake commit together. The wake coalesces per
    recipient (key ``message:<to>``) — a flurry of messages folds into one inbox nudge, and the
    recipient's beat drains the whole inbox.
    """
    with ledger.transaction():
        sent = ledger.messages.send(message)
        wake = ledger.wakes.enqueue(
            Wake(
                id=f"wake_{uuid.uuid4().hex[:12]}",
                employee_id=message.to_employee_id,
                reason=WakeReason.MESSAGE,
                payload={"message_id": sent.id},
                coalesce_key=f"message:{message.to_employee_id}",
            )
        )
    return wake


__all__ = ["assign_task", "deliver_message"]
