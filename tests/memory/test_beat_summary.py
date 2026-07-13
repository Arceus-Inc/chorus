"""Deterministic beat summary for slim recall hits (R8)."""

from __future__ import annotations

import json

import pytest

from chorus.memory import beat_summary

pytestmark = pytest.mark.unit


def _body(text: str) -> str:
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def test_summary_uses_first_narrative_sentence() -> None:
    body = _body("Fixed slugify edge case. Then added tests.")
    assert beat_summary(body, intent="fix slugify") == "Fixed slugify edge case."


def test_summary_truncates_long_narrative() -> None:
    long = "x" * 200
    body = _body(long)
    summary = beat_summary(body, intent="fallback intent")
    assert len(summary) <= 160


def test_summary_falls_back_to_intent_when_body_empty() -> None:
    assert beat_summary("", intent="add truncate helper") == "add truncate helper"


def test_summary_strips_spec_tags() -> None:
    body = _body("<spec>Fixed slugify edge case.</spec> Then added tests.")
    assert beat_summary(body, intent="fix slugify") == "Fixed slugify edge case."
