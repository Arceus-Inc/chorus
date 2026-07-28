"""The render budget — a fixed cap, a fixed order, and a fixed eviction rule.

Nine unbounded string concatenations become one unbounded string concatenation unless the packet has
a hard ceiling and a *deterministic* way of deciding what goes when it is hit. Without this file the
packet is the tenth injection wearing a dataclass.

Two rules the whole module exists to enforce:

- **Eviction is ordered, not incidental.** Sections are ranked once, here. What gets dropped under
  pressure is a property of the design, not of whichever beat happened to be verbose.
- **Eviction is disclosed.** Every trim is reported so the renderer can say so in the output. A
  silently shortened packet is worse than a short one: the model cannot tell "nothing happened on
  this task" from "I was not told what happened on this task", and it will confidently assume the
  first.

Token counts are estimated, never exact. A real tokeniser would mean shipping a model dependency
into the kernel for a number whose only job is to pick a cut-off; a 4-chars-per-token approximation
is wrong by a few percent and costs nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 4
"""Rough English-plus-code ratio. Deliberately approximate — see the module docstring."""

DEFAULT_BUDGET_TOKENS = 2_500
"""Ceiling for the whole rendered packet (~10k characters).

Sized so the packet is a briefing, not a document: large enough to carry a goal chain, a contract and
several prior beats, small enough that it never competes with the work itself for context.
"""


def estimate_tokens(text: str) -> int:
    """Approximate token count for a rendered fragment."""
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def clip(text: str, *, max_tokens: int) -> tuple[str, bool]:
    """Hard-truncate ``text`` to a token ceiling, reporting whether it had to cut.

    The last resort, after a section has already dropped whole items and still does not fit — one
    enormous item, typically. It exists so a section can *guarantee* it stays inside its cap, which
    is what lets :func:`fit` be a genuine safety net rather than the thing that routinely decides
    what a beat is told. Without it, a single oversized entry gets its whole section dropped, and the
    "always keep the most recent attempt" rule quietly stops holding.
    """
    limit = max_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 1)].rstrip() + "…", True


@dataclass(frozen=True)
class SectionBudget:
    """One section's rank, ceiling, and whether it may be dropped whole."""

    name: str
    max_tokens: int
    droppable: bool


SECTION_BUDGETS: tuple[SectionBudget, ...] = (
    # The contract is never dropped: a beat that does not know what "done" means is not a cheaper
    # beat, it is a wasted one.
    SectionBudget("what", max_tokens=400, droppable=False),
    SectionBudget("why", max_tokens=300, droppable=True),
    # The largest allocation, because it is the section the packet exists for.
    SectionBudget("prior_beats", max_tokens=1_000, droppable=True),
    SectionBudget("inbox", max_tokens=300, droppable=True),
    SectionBudget("peers", max_tokens=400, droppable=True),
    # Cheap, and it is what lets a beat trade scope against spend.
    SectionBudget("budget", max_tokens=100, droppable=False),
)
"""Render order and per-section ceilings. Caps sum to :data:`DEFAULT_BUDGET_TOKENS`."""

_BUDGET_BY_NAME = {section.name: section for section in SECTION_BUDGETS}

SECTION_ORDER: tuple[str, ...] = tuple(section.name for section in SECTION_BUDGETS)


def cap_for(name: str) -> int:
    """The token ceiling for one section."""
    return _BUDGET_BY_NAME[name].max_tokens


@dataclass(frozen=True)
class RenderedSection:
    """A section that has already been rendered to text and measured."""

    name: str
    body: str

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.body)


def fit(
    sections: tuple[RenderedSection, ...],
    *,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> tuple[tuple[RenderedSection, ...], tuple[str, ...]]:
    """Keep sections in rank order until the budget is spent; report what was dropped.

    Per-section ceilings are the renderer's job (it owns the structured data and can drop the *oldest*
    beat rather than truncating mid-sentence). This is the second, global gate: it exists for the case
    where a caller passes a budget smaller than the sum of the caps.

    Non-droppable sections are always kept, even if that overshoots — losing the contract to save
    tokens is a false economy, and the overshoot is bounded by their small fixed caps.
    """
    ordered = sorted(sections, key=lambda section: SECTION_ORDER.index(section.name))
    kept: list[RenderedSection] = []
    dropped: list[str] = []
    spent = sum(
        section.tokens for section in ordered if not _BUDGET_BY_NAME[section.name].droppable
    )
    for section in ordered:
        if not _BUDGET_BY_NAME[section.name].droppable:
            kept.append(section)
            continue
        if spent + section.tokens > budget_tokens:
            dropped.append(section.name)
            continue
        spent += section.tokens
        kept.append(section)
    kept.sort(key=lambda section: SECTION_ORDER.index(section.name))
    return tuple(kept), tuple(dropped)


__all__ = [
    "CHARS_PER_TOKEN",
    "DEFAULT_BUDGET_TOKENS",
    "SECTION_BUDGETS",
    "SECTION_ORDER",
    "RenderedSection",
    "SectionBudget",
    "cap_for",
    "clip",
    "estimate_tokens",
    "fit",
]
