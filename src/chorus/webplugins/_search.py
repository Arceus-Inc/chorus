"""Lead-search orchestration — the deterministic control flow of "signal-based prospecting".

A growth team scaling a business hunts for prospects who *just signalled a need* — a CTO stepping
down (interim-leadership gap), a founder asking "can anyone recommend…", a Series-A "building out
the team" post. Those signals live in different places (Google, LinkedIn, X/Twitter, Reddit), so the
hunt is a **query-orchestration loop**: cast many angled queries, read what came back, fix the bad
ones, harvest leads, and stop when fresh queries stop finding fresh names.

This module is the role-agnostic, **dream-free** skeleton of that loop — pure data + pure functions,
fully testable. The *judgment* parts (writing the strategies, healing a query, deciding if a result
is a real buyer) and the *I/O* (actually hitting a search API) are not here: they are the
:data:`~chorus.swarm.LEAD_ORCHESTRATOR` swarm agent's job, acting through its search tools. What lives
here is the mechanical scaffolding that agent reasons *over*: how to read a query's health, how to
dedupe leads, and when the sweep is exhausted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class SearchPlatform(StrEnum):
    """Where a prospecting query runs — each leaves a different "digital footprint" (spec GM §3)."""

    GOOGLE = "google"  # open web: PR, blogs, forums — boolean ``after:`` lookback
    LINKEDIN_NATIVE = "linkedin_native"  # LinkedIn post search via its own API
    LINKEDIN_XRAY = "linkedin_xray"  # Google ``site:linkedin.com/posts`` x-ray
    TWITTER = "twitter"  # X/Twitter real-time solicitation search
    REDDIT = "reddit"  # community advice / technical-pain threads


class QueryLevel(StrEnum):
    """How tightly a query is scoped — the broad→icp funnel an angle is expanded across."""

    BROAD = "broad"  # the widest phrasing of the signal
    INTENT = "intent"  # the signal + a buying-intent cue
    ICP = "icp"  # the signal + intent + an ICP constraint


class QueryHealth(StrEnum):
    """The diagnosis of a probed query — the Observer's branch (spec: query-optimizer Observer)."""

    GHOST_TOWN = "ghost_town"  # too few results: over-constrained / bad syntax — broaden it
    HAYSTACK = "haystack"  # plenty of results but noisy — add a NOT to cut the poison keyword
    HEALTHY = "healthy"  # enough results, signal-rich — keep it


@dataclass(frozen=True)
class LeadQuery:
    """One angled search to run — a platform, a scope level, and the literal query string."""

    platform: SearchPlatform
    level: QueryLevel
    query: str


@dataclass(frozen=True)
class Lead:
    """One harvested prospect — what a search result distils to once classified as a real buyer.

    ``link`` is the dedupe key (the same post surfaced by two queries is one lead); ``body`` is the
    matched snippet the outreach draft is grounded in.
    """

    title: str
    body: str
    link: str
    platform: SearchPlatform


@dataclass(frozen=True)
class DedupeResult:
    """The outcome of deduping a lead batch by link — the unique leads and how many were dropped."""

    leads: tuple[Lead, ...]
    duplicates_removed: int


def classify_query_health(
    result_count: int, *, noisy: bool, min_results: int = 3
) -> QueryHealth:
    """Diagnose a probed query from its yield (spec: query-optimizer Observer ghost-town/haystack).

    Below ``min_results`` the query is a **ghost town** — over-constrained or syntactically wrong, so
    the orchestrator should broaden/heal it. With enough results but the agent flagged them ``noisy``
    (dominated by sellers/job-seekers/news), it is a **haystack** to trim with a NOT operator.
    Otherwise it is **healthy**. ``noisy`` is the upstream judgment; this function is the branch.
    """
    if result_count < min_results:
        return QueryHealth.GHOST_TOWN
    return QueryHealth.HAYSTACK if noisy else QueryHealth.HEALTHY


def dedupe_leads(leads: Iterable[Lead]) -> DedupeResult:
    """Drop leads whose ``link`` was already seen, preserving first-seen order (spec GM §3).

    The sweep runs many overlapping queries, so the same post resurfaces; a prospect is counted once
    by its link. A lead with an empty link is never coalesced (we can't prove it's a duplicate), so
    it is always kept — fail-open on identity, never silently dropping a possibly-distinct prospect.
    """
    seen: set[str] = set()
    unique: list[Lead] = []
    duplicates = 0
    for lead in leads:
        if lead.link and lead.link in seen:
            duplicates += 1
            continue
        if lead.link:
            seen.add(lead.link)
        unique.append(lead)
    return DedupeResult(leads=tuple(unique), duplicates_removed=duplicates)


def lead_dup_rate(leads: Iterable[Lead]) -> float:
    """The fraction of a lead batch that is duplicate links — the saturation signal (spec GM §3).

    As the sweep exhausts a niche, new queries return names already found and the dup rate climbs;
    it is the loop's stop signal. ``0.0`` for an empty batch (nothing found yet, nothing saturated).
    """
    batch = list(leads)
    if not batch:
        return 0.0
    return dedupe_leads(batch).duplicates_removed / len(batch)


def exhaustiveness_stop(
    *, dup_rate: float, loop: int, dup_threshold: float = 0.075, max_loops: int = 5
) -> str | None:
    """Decide whether the prospecting sweep is done — returns the stop reason, or ``None`` to expand.

    Two fail-safe exits (spec: query-optimizer exhaustiveness loop): the sweep has **saturated** once
    duplication crosses ``dup_threshold`` (fresh queries stop finding fresh names), or it has hit its
    **loop budget** (``max_loops``) regardless. ``None`` means keep expanding with new strategies.
    """
    if dup_rate >= dup_threshold:
        return "saturated"
    if loop >= max_loops:
        return "max_loops"
    return None


__all__ = [
    "DedupeResult",
    "Lead",
    "LeadQuery",
    "QueryHealth",
    "QueryLevel",
    "SearchPlatform",
    "classify_query_health",
    "dedupe_leads",
    "exhaustiveness_stop",
    "lead_dup_rate",
]
