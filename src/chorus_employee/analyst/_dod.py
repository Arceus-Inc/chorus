"""The Analyst's Definition of Done — action-class-aware (spec 06 §2; pattern from spec GM §8).

An Analyst mostly writes findings a Reviewer judges — but not every research beat is the same kind of
claim, and a single fixed verifier is either too weak or too heavy for the others. So the DoD *bends
to what the beat produced*, reusing chorus's three existing verifier kinds; the generator just picks
the right one for the action class inferred from the intent:

- a **prediction / model** beat is a :class:`~chorus.outcomes.Command` — an offline held-out scorer
  (``python score.py``) that must exit 0 only when the model clears the agreed metric on data it never
  trained on. This is the *ungameable* floor: a self-reported cross-validation number can be tuned to
  the threshold, but an independent held-out check cannot be — it is machine-checked, free, in-process.
- a **findings / analysis** beat is an :class:`~chorus.outcomes.AgentReview` — a Reviewer reads the
  committed ``findings.md`` and judges whether it answers the question with specific, evidence-backed,
  internally-consistent conclusions (the Analyst's default deliverable).
- a **recommendation / decision** beat is a :class:`~chorus.outcomes.HumanApproval` — when the beat
  asks the Analyst to *recommend* a course of action a human will act on, a person signs off on the
  recommendation. This is a governance gate (should we do what it says?), not a quality gate.

The action class is inferred from the intent by :func:`classify_action`; ``analyst_dod`` maps it to
the verifier. The lander still commits ``findings.md`` in every case — the action class chooses *how*
done is proven, not *what* is landed.
"""

from __future__ import annotations

import re
from enum import StrEnum

from chorus.outcomes import Verifier


class ActionClass(StrEnum):
    """What an Analyst beat produces — the axis its DoD bends to (spec 06 §2; pattern spec GM §8)."""

    PREDICT = "predict"  # a fitted model / forecast → Command (held-out scorer)
    RECOMMEND = "recommend"  # a course of action a human acts on → HumanApproval
    FINDINGS = "findings"  # the default: written, evidence-backed answer → AgentReview


# Keyword cues, checked most-gated first: a recommendation a human will act on dominates (it crosses
# the human sign-off gate), then a prediction/model beat with an objective held-out floor, else the
# default reversible deliverable — reviewed findings.
_RECOMMEND_CUES = (
    "recommend",
    "recommendation",
    "decide",
    "decision",
    "should we",
    "go/no-go",
    "go no-go",
    "propose",
    "proposal",
    "advise",
    "pick",
    "choose",
    "prioritize",
    "prioritise",
)
# Only an UNAMBIGUOUS predictive vocabulary — words that in ordinary research/analysis prose mean
# something else are deliberately excluded: "model" (a language-model / data-model / business-model,
# and it false-fires inside hyphenated compounds like "large-language-model" where the hyphen is a
# word boundary), "fit" (goodness-of-fit), "score" (a credit score / "is this a good score"), and bare
# "accuracy". A genuine prediction beat still lands here via predict/forecast/classify/train/etc.
_PREDICT_CUES = (
    "predict",
    "prediction",
    "predictive",
    "forecast",
    "classify",
    "classifier",
    "train",
    "regression",
    "backtest",
    "back-test",
    "holdout",
    "hold-out",
    "auc",
    "rmse",
)


def _cue_matcher(cues: tuple[str, ...]) -> re.Pattern[str]:
    """Compile cues into a whole-word matcher (optional plural ``s``) so substrings don't false-match.

    Plain ``cue in text`` mis-fires — ``"train"`` in "restrained", ``"forecast"`` in "forecaster". A
    word boundary plus an optional trailing ``s`` matches "forecast"/"forecasts" while skipping those.
    Word boundaries do NOT protect against hyphenated compounds (a hyphen is itself a boundary), so a
    cue that appears inside a domain compound — e.g. "model" in "large-language-model" — must simply
    be kept out of the cue list rather than relied on to be bounded.
    """
    alternation = "|".join(re.escape(cue) for cue in cues)
    return re.compile(rf"\b(?:{alternation})s?\b")


_RECOMMEND_RE = _cue_matcher(_RECOMMEND_CUES)
_PREDICT_RE = _cue_matcher(_PREDICT_CUES)

_FINDINGS_RUBRIC = (
    "You are judging a FINISHED artifact: the file `findings.md` produced by an analyst. Use "
    "`read_file` to read `findings.md` (you have read_file). PASS it when `findings.md` is present, "
    "non-empty, and answers every part of the task's question with specific, numeric, evidence-backed "
    "conclusions that are internally consistent. You are read-only by design: you do NOT have, and do "
    "NOT need, warehouse_query / notebook_run / a shell / subagents, and you must NOT require re-running "
    "queries, re-executing code, STDOUT logs, regenerated charts, or any other process evidence — the "
    "committed `findings.md` IS the evidence. Never claim you cannot verify: read the file and assess "
    "its content. You also have NO web or browser tool and CANNOT open the URLs a claim cites — that is "
    "by design; a citation you cannot personally fetch is NOT grounds to fail. Judge whether each claim "
    "carries a plausible, relevant source and whether the numbers and reasoning are internally "
    "consistent — not whether you can re-fetch the page. Judge citations by SUBSTANCE, not format: a "
    "claim is supported if it carries a source "
    "the analyst could have retrieved — an API endpoint, a raw file, a docs page, or an HTML page are "
    "ALL valid; never fail a finding for the *kind* of URL it cites, and never invent a citation-format "
    "rule the task did not state. Hold a CONVERGENCE bar: PASS as soon as every question the task asked "
    "is answered with specific, sourced, self-consistent conclusions — approve work that is materially "
    "complete even if it could be marginally improved, and do NOT withhold approval for stylistic "
    "polish, per-sentence citation adjacency, belt-and-suspenders evidence, or anything the task did not "
    "require. FAIL only for a CONCRETE defect: `findings.md` missing, a required answer absent or vague, "
    "a self-contradiction (e.g. an impossible or future-dated claim), or a factual claim with no source "
    "at all — and when you fail, name the specific fix so the next attempt can converge."
)


def classify_action(intent: str) -> ActionClass:
    """Infer the action class from a beat's intent — most-gated cue wins (spec 06 §2; pattern GM §8)."""
    text = intent.lower()
    if _RECOMMEND_RE.search(text):
        return ActionClass.RECOMMEND
    if _PREDICT_RE.search(text):
        return ActionClass.PREDICT
    return ActionClass.FINDINGS


def analyst_dod(intent: str) -> Verifier:
    """The Analyst's DoD generator (spec 04): the verifier kind for the beat's action class."""
    action = classify_action(intent)
    if action is ActionClass.RECOMMEND:
        # A recommendation a human will act on is a governance gate, not a quality gate.
        return Verifier.human_approval(artifact_class="recommendation")
    if action is ActionClass.PREDICT:
        # Offline, verifiable, free: an independent held-out scorer is the objective floor a
        # self-reported metric cannot fake (fixes cross-validation gaming).
        return Verifier.command("python score.py", artifact_class="prediction", timeout_s=600)
    return Verifier.agent_review(rubric=_FINDINGS_RUBRIC, artifact_class="finding")


__all__ = ["ActionClass", "analyst_dod", "classify_action"]
