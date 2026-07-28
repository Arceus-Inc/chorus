"""The task-context packet — one typed answer to "what does this beat need to know?".

The packet is a **pure projection of durable rows, keyed by ``task_id``**. That key is the whole
point: a beat's identity in dream is its ``run_id``, so everything dream writes (plan, sprint
contract, transcript, working memory) dies with the beat. Keying the packet to the *task* makes the
next beat's context a re-derivation rather than a recovery — no session to persist, no transcript to
replay, no checkpointing to maintain.

Nothing here reads a model or mutates state. Same rows in, byte-identical packet out, which is what
makes the whole surface snapshot-testable — and what lets a misbehaving beat be diagnosed by
diffing its packet instead of re-reading a prompt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PACKET_VERSION = 1
"""Bumped whenever a field is added, removed, or changes meaning.

Persisted alongside the packet so a stored ``task-context.json`` from an older build is recognisable
rather than silently misread.
"""

SUMMARY_CAP_CHARS = 600
"""Per-beat cap applied to an episodic body *at projection time*, not at render time.

Capping late would mean carrying tens of KB through the packet only to drop it; capping here keeps
the projection itself bounded.
"""

DEFAULT_MAX_PRIOR_BEATS = 5
"""How many previous beats to project. The renderer's budget may show fewer, never more."""

SCOPE_GUARD = (
    "Stay inside the assigned scope. The parent objective above is context for keeping this task "
    "faithful to what was delegated — it is not permission to widen the work."
)
"""The scope rule, stated once.

It currently lives inline in the *user message* via ``_execution_intent``'s ancestor stuffing. It
belongs to the contract, not the instruction, so the packet owns it and the stuffing can go.
"""


@dataclass(frozen=True)
class GoalLink:
    """One rung of the why-chain — a goal above this task, or a task that delegated to it."""

    kind: str  # "goal" | "task"
    id: str
    title: str
    status: str


@dataclass(frozen=True)
class Contract:
    """What "done" means for this task, taken verbatim from the ``dod`` row.

    Verbatim matters: a paraphrased DoD is a different DoD, and the evaluator is judging against the
    real one.
    """

    intent: str
    dod_kind: str | None = None
    dod_spec: str = ""
    artifact_class: str | None = None
    scope_guard: str = SCOPE_GUARD


@dataclass(frozen=True)
class PriorBeat:
    """One previous run on **this** task — the packet's reason to exist.

    Without this section a second beat re-derives its understanding from files alone and reaches a
    different conclusion than the first. ``verdict_notes`` is the specific fix for repeating a
    defect the evaluator already named.
    """

    run_id: str
    beat_number: int
    employee_id: str
    status: str
    phase: str | None = None
    recovery_hint: str | None = None
    passed: bool | None = None
    outcome: str = ""
    score: float = 0.0
    files_touched: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    verdict_notes: tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True)
class InboxItem:
    """One unread message addressed to this employee."""

    message_id: str
    from_id: str
    body: str
    task_id: str | None = None


@dataclass(frozen=True)
class PeerWork:
    """A sibling task and the files it claims. Populated once tasks declare a write scope."""

    task_id: str
    intent: str
    status: str
    assignee_employee_id: str | None = None
    files_claimed: tuple[str, ...] = ()
    is_live: bool = False


@dataclass(frozen=True)
class BudgetPosition:
    """Spend so far against the cap, so scope can be traded against cost inside the beat."""

    spent_cents: int
    limit_cents: int | None
    beat_number: int


@dataclass(frozen=True)
class TaskContextPacket:
    """Everything the kernel can tell a beat, derived from rows that already exist."""

    task_id: str
    run_id: str
    employee_id: str
    role: str
    what: Contract
    budget: BudgetPosition
    packet_version: int = PACKET_VERSION
    why: tuple[GoalLink, ...] = ()
    prior_beats: tuple[PriorBeat, ...] = ()
    inbox: tuple[InboxItem, ...] = ()
    peers: tuple[PeerWork, ...] = ()
    truncated: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_first_beat(self) -> bool:
        """True when nothing has been attempted on this task yet.

        The renderer says so explicitly rather than omitting the section: "no prior beats" and "I
        wasn't told about prior beats" must not look the same to the model.
        """
        return not self.prior_beats

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-able form — what gets written to the worktree for tools and snapshot tests.

        Returns JSON-*native* types: tuples become lists, so ``json.loads(json.dumps(p.to_dict()))``
        equals ``p.to_dict()``. Without that a reader who compares the on-disk packet against a
        freshly projected one gets a confusing mismatch on every sequence field, and the file stops
        being a usable diff target — which is most of the reason it is written at all.
        """
        return dict(_jsonable(asdict(self)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "DEFAULT_MAX_PRIOR_BEATS",
    "PACKET_VERSION",
    "SCOPE_GUARD",
    "SUMMARY_CAP_CHARS",
    "BudgetPosition",
    "Contract",
    "GoalLink",
    "InboxItem",
    "PeerWork",
    "PriorBeat",
    "TaskContextPacket",
]
