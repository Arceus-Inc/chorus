"""Decompose seeds repo/AGENTS.md so the coherence contract always exists (spec 15 §4.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.lifecycle import seed_agents_md

pytestmark = pytest.mark.unit


def test_seed_writes_a_skeleton_when_absent(tmp_path: Path) -> None:
    seed_agents_md(tmp_path, goal_intent="Build dpo_tune: a Trainer + dpo_loss")
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Module map" in text
    assert "## Public API" in text
    assert "## Ownership" in text


def test_seed_does_not_clobber_an_existing_contract(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# AGENTS.md\nhand-authored\n", encoding="utf-8")
    seed_agents_md(tmp_path, goal_intent="x")
    assert "hand-authored" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
