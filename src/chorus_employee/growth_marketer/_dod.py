"""The Growth Marketer's Definition of Done — action-class-aware (spec GM §8).

Mira's DoD *bends to the action class* — "done" is never just "tests exit 0", because her actions can
spend money and reach real users. She reuses chorus's three existing verifier kinds; the generator
just picks the right one for what the beat produced:

- a **back-test / holdout** is a :class:`~chorus.outcomes.Command` — an offline script that must clear
  a lift threshold (machine-checkable, free, in-process);
- a **campaign brief** is an :class:`~chorus.outcomes.AgentReview` — a Growth Reviewer checks the
  hypothesis, audience, sample size, and that the copy is on-brand & compliant;
- a **live send / ad spend** is a :class:`~chorus.outcomes.HumanApproval` — a person approves the
  spend, the audience, and the final creative (a governance gate, not a quality gate);
- a **content batch** (posts/reels/blogs to publish) is also a :class:`~chorus.outcomes.HumanApproval`
  — the "swipe" gate over the drafts, since publishing reaches real users on a capped channel.

The action class is inferred from the intent by :func:`classify_action`, shared with the lander so the
verifier and the landed artifact always agree.
"""

from __future__ import annotations

import re
from enum import StrEnum

from chorus.outcomes import Verifier


class ActionClass(StrEnum):
    """What a Growth Marketer beat produces — the axis her DoD and outcome bend to (spec GM §8)."""

    BACKTEST = "backtest"  # offline eval → Command → backtest_report
    BRIEF = "brief"  # a plan/brief → AgentReview → campaign_brief
    CONTENT = "content"  # a batch of drafts to publish → HumanApproval (swipe) → campaign_content
    LAUNCH = "launch"  # spend / live send → HumanApproval → experiment_launched


# Keyword cues, checked most-gated first: a live send or spend dominates (it crosses the human gate),
# then a content batch to publish (a swipe-gated send), then an offline back-test, else the default
# reversible deliverable — a reviewed brief.
_LAUNCH_CUES = ("launch", "send", "spend", "go live", "live send", "ad budget", "allocate budget", "ship")
_CONTENT_CUES = (
    "post", "reel", "tweet", "blog", "social", "newsletter", "content", "caption", "publish", "creative",
)
_BACKTEST_CUES = ("backtest", "back-test", "holdout", "hold-out", "offline eval", "power calc", "simulate")


def _cue_matcher(cues: tuple[str, ...]) -> re.Pattern[str]:
    """Compile cues into a whole-word matcher (optional plural ``s``) so substrings don't false-match.

    Plain ``cue in text`` mis-fires — ``"send"`` in "resend", ``"ship"`` in "relationship",
    ``"post"`` in "postpone". A word boundary plus an optional trailing ``s`` matches "post"/"posts"
    while skipping those, so a beat lands the gate its *words* call for, not an accidental substring.
    """
    alternation = "|".join(re.escape(cue) for cue in cues)
    return re.compile(rf"\b(?:{alternation})s?\b")


_LAUNCH_RE = _cue_matcher(_LAUNCH_CUES)
_CONTENT_RE = _cue_matcher(_CONTENT_CUES)
_BACKTEST_RE = _cue_matcher(_BACKTEST_CUES)

_BRIEF_RUBRIC = (
    "the hypothesis is sound, the target audience is right and adequately sized, and the copy is "
    "on-brand and compliant; the brief is present, specific, and ready to act on"
)


def classify_action(intent: str) -> ActionClass:
    """Infer the action class from a beat's intent — most-gated cue wins (spec GM §8, §9)."""
    text = intent.lower()
    if _LAUNCH_RE.search(text):
        return ActionClass.LAUNCH
    if _CONTENT_RE.search(text):
        return ActionClass.CONTENT
    if _BACKTEST_RE.search(text):
        return ActionClass.BACKTEST
    return ActionClass.BRIEF


def growth_marketer_dod(intent: str) -> Verifier:
    """The Growth Marketer's DoD generator (spec GM §8): the verifier kind for the beat's action class."""
    action = classify_action(intent)
    if action is ActionClass.LAUNCH:
        # A live send / ad spend is a governance gate, not a quality gate (spec GM §8).
        return Verifier.human_approval(artifact_class="experiment_launched")
    if action is ActionClass.CONTENT:
        # The swipe gate: a person accepts/rejects the drafts before any of them publish (§3, §9).
        return Verifier.human_approval(artifact_class="campaign_content")
    if action is ActionClass.BACKTEST:
        # Offline, verifiable, free: the back-test script is the objective floor (spec GM §8).
        return Verifier.command(
            "python backtest.py", artifact_class="backtest_report", timeout_s=600
        )
    return Verifier.agent_review(rubric=_BRIEF_RUBRIC, artifact_class="campaign_brief")


__all__ = ["ActionClass", "classify_action", "growth_marketer_dod"]
