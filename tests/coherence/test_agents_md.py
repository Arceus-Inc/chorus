"""AGENTS.md codec — the canonical cross-child contract (spec 15 §4.1)."""

from __future__ import annotations

import pytest

from chorus.coherence import AgentsMd

pytestmark = pytest.mark.unit

_SAMPLE = """# AGENTS.md

## Module map
- `dpo_tune/__init__.py` — package entry; re-exports the public API
- `dpo_tune/trainer.py` — Trainer.fit()

## Public API
- `dpo_tune.Trainer`
- `dpo_tune.dpo_loss`

## Ownership
- `dpo_tune/trainer.py` -> ada
- `dpo_tune/loss.py` -> bo
"""


def test_parse_extracts_the_three_sections() -> None:
    doc = AgentsMd.parse(_SAMPLE)
    assert doc.modules == ("dpo_tune/__init__.py", "dpo_tune/trainer.py")
    assert doc.public_api == ("dpo_tune.Trainer", "dpo_tune.dpo_loss")
    assert doc.ownership == {"dpo_tune/trainer.py": "ada", "dpo_tune/loss.py": "bo"}


def test_render_round_trips() -> None:
    doc = AgentsMd.parse(_SAMPLE)
    assert AgentsMd.parse(doc.render()) == doc


def test_parse_is_forgiving_of_blank_and_missing_sections() -> None:
    doc = AgentsMd.parse("# AGENTS.md\n\n## Public API\n- `pkg.Thing`\n")
    assert doc.public_api == ("pkg.Thing",)
    assert doc.modules == ()
    assert doc.ownership == {}


def test_arrow_unicode_and_ascii_both_parse() -> None:
    doc = AgentsMd.parse("# AGENTS.md\n## Ownership\n- `a.py` → x\n- `b.py` -> y\n")
    assert doc.ownership == {"a.py": "x", "b.py": "y"}
