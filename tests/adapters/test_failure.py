"""The four-way failure contract classifies a beat raise, and flags transient ones retryable (spec 05 §5).

A ``*HeadParseError`` (planner/evaluator/generator emitted unparseable structured output) is a
*transient* fault — re-running the beat usually clears it — so the adapter marks it ``retryable`` while
keeping it an ``ERRORED`` disposition. Every other engine fault stays a non-retryable error; a
cooperative cancel is unchanged.
"""

from __future__ import annotations

import pytest

from chorus.adapters._failure import failure_outcome
from chorus.heartbeat._beat import BeatDisposition

pytestmark = pytest.mark.unit


class PlannerHeadParseError(RuntimeError):
    """Mirror of dream's class name (the adapter classifies structurally, by name)."""


class EvaluatorHeadParseError(RuntimeError): ...


class _Cancelled(Exception):
    code = "dream.cancelled"


def test_head_parse_error_is_errored_but_retryable() -> None:
    outcome = failure_outcome(PlannerHeadParseError("planner reply missing <spec>...</spec> section"))
    assert outcome.disposition is BeatDisposition.ERRORED
    assert outcome.retryable is True
    assert "PlannerHeadParseError" in str(outcome.outcome["error"])


def test_every_head_parse_variant_is_retryable() -> None:
    assert failure_outcome(EvaluatorHeadParseError("bad")).retryable is True


def test_generic_engine_fault_is_not_retryable() -> None:
    outcome = failure_outcome(RuntimeError("disk on fire"))
    assert outcome.disposition is BeatDisposition.ERRORED
    assert outcome.retryable is False


def test_cancelled_is_unchanged_and_not_retryable() -> None:
    outcome = failure_outcome(_Cancelled())
    assert outcome.disposition is BeatDisposition.CANCELLED
    assert outcome.retryable is False
