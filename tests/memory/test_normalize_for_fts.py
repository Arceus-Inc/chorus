"""Normalize episodic prose before FTS indexing — strip tag/markup noise."""

from __future__ import annotations

import json

import pytest

from chorus.memory.episodic.narrative import narrative, normalize_for_fts

pytestmark = pytest.mark.unit


def test_strips_xml_like_tags_and_collapses_whitespace() -> None:
    raw = "<spec>  fix   slugify  </spec>\n\nthen <proposal>add tests</proposal>"
    assert normalize_for_fts(raw) == "fix slugify then add tests"


def test_index_path_normalizes_role_text() -> None:
    body = json.dumps(
        {
            "kind": "role.text",
            "role": "generator",
            "text": "<spec>implement slugify</spec>  edge  cases",
        }
    )
    assert normalize_for_fts(narrative(body)) == "implement slugify edge cases"
    assert "<spec>" in narrative(body)
