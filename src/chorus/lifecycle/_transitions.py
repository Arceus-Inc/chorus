"""The task status machine (spec 02 §2).

The legal-transition table, the terminal set, and the entry-timestamp stamping —
transplanted verbatim from Paperclip's ``execution-semantics.md`` and adapted for
chorus. The single load-bearing rule beyond pure edge-legality: **entering
``in_progress`` happens by checkout, never by a bare status PATCH** — so a status
change can never silently mint an agent-owned, execution-backed task without the
atomic checkout CAS (spec 01) behind it.

```
backlog ──▶ todo ──▶ in_progress ──▶ in_review ──▶ done
   │          │           │   │  ▲         │
   │          │           │   │  └─────────┘ (changes requested)
   ▼          ▼           ▼   ▼
cancelled  blocked ◀──────┘  done
```
"""

from __future__ import annotations

from chorus.errors import ChorusError
from chorus.ledger._models import TaskStatus

# The legal transitions (spec 02 §2). Terminal states map to an empty set.
LEGAL_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.BACKLOG: frozenset({TaskStatus.TODO, TaskStatus.CANCELLED}),
    TaskStatus.TODO: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {TaskStatus.IN_REVIEW, TaskStatus.BLOCKED, TaskStatus.DONE, TaskStatus.CANCELLED,
         TaskStatus.REJECTED}
    ),
    TaskStatus.IN_REVIEW: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED}
    ),
    TaskStatus.BLOCKED: frozenset(
        {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED, TaskStatus.REJECTED}
    ),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.REJECTED: frozenset(),
}

# Terminal statuses — no legal outgoing transition (spec 02 §2). ``REJECTED`` is terminal-by-review:
# the work attempt is closed (so a parent's ``children_done`` fires and the manager reacts with a fresh
# ``submit_task`` rather than reopening the rejected attempt).
TERMINAL: frozenset[TaskStatus] = frozenset(
    {TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED}
)

# The ``*_at`` column stamped on entry into a status (spec 02 §2). Absent => no stamp.
_ENTRY_STAMP: dict[TaskStatus, str] = {
    TaskStatus.IN_PROGRESS: "started_at",
    TaskStatus.DONE: "completed_at",
    TaskStatus.CANCELLED: "cancelled_at",
}


class IllegalTransition(ChorusError):
    """A status transition that the machine forbids (spec 02 §2)."""

    code = "chorus.lifecycle.illegal_transition"


def is_legal(current: TaskStatus, target: TaskStatus) -> bool:
    """True iff ``current → target`` is a legal edge (spec 02 §2).

    Pure edge-legality only — it does **not** encode the checkout rule (a legal
    ``→ in_progress`` edge still returns ``True`` here); :func:`assert_legal`
    layers that on top.
    """
    return target in LEGAL_TRANSITIONS[current]


def assert_legal(
    current: TaskStatus, target: TaskStatus, *, via_checkout: bool = False
) -> None:
    """Raise :class:`IllegalTransition` unless ``current → target`` is allowed.

    Beyond edge-legality, enforces the checkout rule: entering ``in_progress`` is
    only valid through checkout (``via_checkout=True``); a bare status PATCH into
    ``in_progress`` is rejected even though the edge itself is legal (spec 02 §2).
    """
    if not is_legal(current, target):
        raise IllegalTransition(
            f"illegal transition {current.value} → {target.value}"
        )
    if target is TaskStatus.IN_PROGRESS and not via_checkout:
        raise IllegalTransition(
            f"{current.value} → in_progress must go through checkout, not a bare status PATCH"
        )


def entry_stamp(target: TaskStatus) -> str | None:
    """The ``*_at`` column to stamp on entry into ``target``, or ``None`` (spec 02 §2)."""
    return _ENTRY_STAMP.get(target)


__all__ = [
    "LEGAL_TRANSITIONS",
    "TERMINAL",
    "IllegalTransition",
    "assert_legal",
    "entry_stamp",
    "is_legal",
]
