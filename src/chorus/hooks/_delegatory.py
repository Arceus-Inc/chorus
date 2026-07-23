"""The delegatory message hook — an instruction becomes work, not inbox residue.

Paperclip's model: tasks and comments are the only channel, and a directed instruction IS a
task waiting to exist. When an employee (or the human on the board) sends an INSTRUCTION
message, this hook opens a real ``todo`` task for the recipient — fingerprinted by the message
id so re-runs are no-ops — inheriting the thread task's goal (the why-chain survives the hop),
and consumes the inbox nudge: the recipient's next beat finds a work item on the board instead
of prose to interpret. FYI/reply/escalation messages are left for the beat brief.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from chorus.ledger import MessageKind, OriginKind, Task, TaskStatus

if TYPE_CHECKING:
    from chorus.ledger import Ledger


def instruction_messages_become_tasks(ledger: Ledger) -> int:
    fired = 0
    for employee in ledger.employees.list():
        for message in ledger.messages.inbox(employee.id):
            if message.kind is not MessageKind.INSTRUCTION:
                continue
            fingerprint = f"message:{message.id}"
            if ledger.tasks.find_by_origin(OriginKind.MANUAL, fingerprint) is None:
                thread = ledger.tasks.get(message.task_id) if message.task_id else None
                sender = message.from_employee_id or message.from_user_id or "the board"
                ledger.tasks.submit(
                    Task(
                        id=str(uuid.uuid4()),
                        intent=f"[from {sender}] {message.body}",
                        status=TaskStatus.TODO,
                        assignee_employee_id=employee.id,
                        goal_id=thread.goal_id if thread is not None else None,
                        origin_kind=OriginKind.MANUAL,
                        origin_fingerprint=fingerprint,
                        created_by_employee_id=message.from_employee_id,
                        created_by_user_id=message.from_user_id,
                    )
                )
                fired += 1
            ledger.messages.mark_read(message.id)  # consumed into work either way
    return fired


__all__ = ["instruction_messages_become_tasks"]
