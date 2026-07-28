"""Render a :class:`TaskContextPacket` as the markdown a beat actually reads.

Pure and deterministic: same packet plus same audience plus same budget yields byte-identical text.
That is what makes the output snapshot-testable, and it is what turns "the model behaved oddly" into
a diff rather than an argument.

Three things this module is deliberate about:

- **Audience, not a boolean.** The three dream roles need three different views, and the difference
  that matters is not cosmetic (see :class:`ContextAudience`).
- **Absence is stated.** "No prior beats" is rendered explicitly rather than by omitting the heading,
  because a model cannot distinguish a missing section from an empty one and will fill the gap with
  an assumption.
- **Every trim is announced** in the text itself, with the tool call that recovers what was dropped.
"""

from __future__ import annotations

from enum import StrEnum

from chorus.context._budget import (
    DEFAULT_BUDGET_TOKENS,
    RenderedSection,
    cap_for,
    clip,
    estimate_tokens,
    fit,
)
from chorus.context._packet import (
    BudgetPosition,
    Contract,
    GoalLink,
    InboxItem,
    PeerWork,
    PriorBeat,
    TaskContextPacket,
)


class ContextAudience(StrEnum):
    """Which dream role is reading, and therefore which sections it gets.

    ``write_role_overlays`` writes the same ``system_prompt`` into all three dream role overlays, so
    an unqualified append hands the whole packet to the evaluator as well. That is the wrong default:

    - **planner** is *toolless*. It cannot call ``recall`` even in principle, so it is the role that
      most needs history pushed to it — and today the one that gets least. Giving it prior beats is
      what stops beat N+1 re-planning straight back into the shape beat N had rejected.
    - **generator** does the work and gets everything.
    - **evaluator** is judging *this* beat's artifact against the contract and the oracle. Telling it
      "attempt 3, previously rejected for X" makes its verdict path-dependent — the same artifact
      would be judged differently depending on what came before it, which is precisely the property a
      gate must not have.
    """

    PLANNER = "planner"
    GENERATOR = "generator"
    EVALUATOR = "evaluator"


_SECTIONS_BY_AUDIENCE: dict[ContextAudience, frozenset[str]] = {
    ContextAudience.PLANNER: frozenset({"why", "what", "prior_beats", "budget"}),
    ContextAudience.GENERATOR: frozenset(
        {"why", "what", "prior_beats", "inbox", "peers", "budget"}
    ),
    ContextAudience.EVALUATOR: frozenset({"why", "what"}),
}

_HEADER = "## Task context"
_RECOVER_HINT = "call `get_run(run_id=…)` for the full account"


def sections_for(audience: ContextAudience) -> frozenset[str]:
    """The section names one audience receives."""
    return _SECTIONS_BY_AUDIENCE[audience]


def render(
    packet: TaskContextPacket,
    *,
    audience: ContextAudience = ContextAudience.GENERATOR,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> RenderedContext:
    """Render the packet for one audience within a token budget."""
    allowed = sections_for(audience)
    trimmed: list[str] = []
    candidates: list[RenderedSection] = []

    for name, body in (
        ("what", _render_what(packet.what)),
        ("why", _render_why(packet.why, trimmed)),
        ("prior_beats", _render_prior_beats(packet.prior_beats, trimmed)),
        ("inbox", _render_inbox(packet.inbox, trimmed)),
        ("peers", _render_peers(packet.peers, trimmed)),
        ("budget", _render_budget(packet.budget)),
    ):
        if name in allowed and body:
            candidates.append(RenderedSection(name=name, body=body))

    kept, dropped = fit(tuple(candidates), budget_tokens=budget_tokens)
    body = "\n\n".join(section.body for section in kept)
    text = f"{_HEADER}\n\n{body}" if body else ""
    truncated = tuple(dict.fromkeys([*trimmed, *dropped]))
    return RenderedContext(text=text, truncated=truncated, tokens=estimate_tokens(text))


class RenderedContext:
    """The rendered text plus what it had to leave out.

    Returned rather than folded back onto the packet so the packet stays a pure projection of the
    ledger: what a beat *was told* depends on the audience and the budget, which are render-time
    concerns. The caller carries ``truncated`` back onto the persisted copy so the on-disk record and
    the prompt agree about what was shown.
    """

    __slots__ = ("text", "tokens", "truncated")

    def __init__(self, *, text: str, truncated: tuple[str, ...], tokens: int) -> None:
        self.text = text
        self.truncated = truncated
        self.tokens = tokens

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RenderedContext(tokens={self.tokens}, truncated={self.truncated!r})"


def _capped(name: str, body: str, trimmed: list[str]) -> str:
    """Guarantee a section body stays inside its own ceiling.

    Item-level eviction runs first and is preferable — dropping the oldest beat reads better than
    cutting one mid-sentence. This is the backstop for when a single item is itself over the cap,
    and it is what keeps :func:`fit` a safety net instead of the thing that routinely decides what a
    beat is told.
    """
    clipped, was_clipped = clip(body, max_tokens=cap_for(name))
    if was_clipped and name not in trimmed:
        trimmed.append(name)
    return clipped


def _render_what(what: Contract) -> str:
    lines = ["### What done means", "", what.intent.strip()]
    if what.dod_kind:
        label = "Command" if what.dod_kind == "command" else what.dod_kind.replace("_", " ").title()
        lines.append("")
        lines.append(f"**Definition of done ({label}):** {what.dod_spec or '(unspecified)'}")
    else:
        lines.append("")
        lines.append("**Definition of done:** none recorded for this task.")
    if what.artifact_class:
        lines.append(f"**Artifact class:** {what.artifact_class}")
    lines.append("")
    lines.append(what.scope_guard)
    return "\n".join(lines)


def _render_why(why: tuple[GoalLink, ...], trimmed: list[str]) -> str:
    if not why:
        return ""
    # Root and immediate parent are the two rungs that carry meaning; the middle of a deep chain is
    # restatement. Keeping the ends rather than a prefix is what preserves "why" under pressure.
    kept = list(why)
    dropped = 0
    while len(kept) > 2 and estimate_tokens(_why_body(kept)) > cap_for("why"):
        del kept[1]
        dropped += 1
    if dropped:
        trimmed.append("why")
    lines = ["### Why this task exists", "", _capped("why", _why_body(kept), trimmed)]
    if dropped:
        lines.append("")
        lines.append(f"_{dropped} intermediate level(s) omitted._")
    return "\n".join(lines)


def _why_body(links: list[GoalLink]) -> str:
    return "\n".join(
        f"- **{link.kind}** `{link.id}` — {link.title} _({link.status})_" for link in links
    )


def _render_prior_beats(beats: tuple[PriorBeat, ...], trimmed: list[str]) -> str:
    if not beats:
        # Stated, not omitted — see the module docstring.
        return "### Where you left off\n\nThis is the first beat on this task. Nothing has been\nattempted yet."
    kept = list(beats)
    dropped = 0
    # Newest last, so evict from the front: the most recent attempt is the one worth carrying.
    while kept and estimate_tokens(_beats_body(kept)) > cap_for("prior_beats") and len(kept) > 1:
        del kept[0]
        dropped += 1
    if dropped:
        trimmed.append("prior_beats")
    heading = f"### Where you left off — {len(beats)} prior beat(s) on this task"
    lines = [heading, "", _capped("prior_beats", _beats_body(kept), trimmed)]
    if dropped:
        lines.append("")
        lines.append(f"_{dropped} earlier beat(s) omitted — {_RECOVER_HINT}._")
    return "\n".join(lines)


def _beats_body(beats: list[PriorBeat]) -> str:
    return "\n\n".join(_one_beat(beat) for beat in beats)


def _one_beat(beat: PriorBeat) -> str:
    verdict = beat.phase or beat.outcome or beat.status
    lines = [f"**Beat {beat.beat_number}** · `{beat.run_id}` · {verdict}"]
    if beat.recovery_hint and beat.recovery_hint != "none":
        lines.append(f"- next step: **{beat.recovery_hint}**")
    if beat.files_touched:
        lines.append(f"- files touched: {', '.join(f'`{path}`' for path in beat.files_touched)}")
    if beat.artifacts:
        lines.append(f"- artifacts: {', '.join(beat.artifacts)}")
    for note in beat.verdict_notes:
        lines.append(f"- evaluator: {note}")
    if beat.summary:
        lines.append(f"- account: {beat.summary}")
    return "\n".join(lines)


def _render_inbox(inbox: tuple[InboxItem, ...], trimmed: list[str]) -> str:
    if not inbox:
        return ""
    kept = list(inbox)
    dropped = 0
    while kept and estimate_tokens(_inbox_body(kept)) > cap_for("inbox") and len(kept) > 1:
        del kept[0]  # oldest first
        dropped += 1
    if dropped:
        trimmed.append("inbox")
    lines = ["### Unread messages", "", _capped("inbox", _inbox_body(kept), trimmed)]
    if dropped:
        lines.append("")
        lines.append(
            f"_{dropped} older message(s) omitted — read the thread with `read_comments`._"
        )
    return "\n".join(lines)


def _inbox_body(inbox: list[InboxItem]) -> str:
    return "\n".join(
        f"- from **{item.from_id}**"
        + (f" (task `{item.task_id}`)" if item.task_id else "")
        + f": {item.body}"
        for item in inbox
    )


def _render_peers(peers: tuple[PeerWork, ...], trimmed: list[str]) -> str:
    if not peers:
        return ""
    # Live peers are the ones that can collide with this beat; a finished sibling is history.
    kept = sorted(peers, key=lambda peer: (not peer.is_live, peer.task_id))
    dropped = 0
    while kept and estimate_tokens(_peers_body(kept)) > cap_for("peers") and len(kept) > 1:
        kept.pop()
        dropped += 1
    if dropped:
        trimmed.append("peers")
    lines = ["### What your peers are building", "", _capped("peers", _peers_body(kept), trimmed)]
    if dropped:
        lines.append("")
        lines.append(f"_{dropped} peer task(s) omitted._")
    return "\n".join(lines)


def _peers_body(peers: list[PeerWork]) -> str:
    rows = []
    for peer in peers:
        live = " · **in flight**" if peer.is_live else ""
        claim = (
            f" — claims {', '.join(f'`{path}`' for path in peer.files_claimed)}"
            if peer.files_claimed
            else ""
        )
        owner = peer.assignee_employee_id or "unassigned"
        rows.append(f"- `{peer.task_id}` ({owner}, {peer.status}){live}: {peer.intent}{claim}")
    return "\n".join(rows)


def _render_budget(budget: BudgetPosition) -> str:
    spend = f"{budget.spent_cents} cents spent"
    if budget.limit_cents:
        remaining = max(0, budget.limit_cents - budget.spent_cents)
        spend += f" of {budget.limit_cents} · {remaining} remaining"
    return f"### Budget\n\nBeat {budget.beat_number} · {spend}"


__all__ = ["ContextAudience", "RenderedContext", "render", "sections_for"]
