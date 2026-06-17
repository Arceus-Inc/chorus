"""The ``.env`` loader: parse ``KEY=VALUE`` lines into a target environment."""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus_cli._env import load_env_file

pytestmark = pytest.mark.unit


def test_loads_simple_pairs(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nB=two\n", encoding="utf-8")
    target: dict[str, str] = {}
    loaded = load_env_file(env_file, environ=target)
    assert loaded == 2
    assert target == {"A": "1", "B": "two"}


def test_skips_blanks_and_comments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\n\nA=1\n   # indented comment\n", encoding="utf-8")
    target: dict[str, str] = {}
    assert load_env_file(env_file, environ=target) == 1
    assert target == {"A": "1"}


def test_strips_export_prefix_and_surrounding_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('export A="quoted value"\nB=\'single\'\n', encoding="utf-8")
    target: dict[str, str] = {}
    load_env_file(env_file, environ=target)
    assert target == {"A": "quoted value", "B": "single"}


def test_value_may_contain_equals_signs(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("URL=https://x/openai/v1?k=v\n", encoding="utf-8")
    target: dict[str, str] = {}
    load_env_file(env_file, environ=target)
    assert target["URL"] == "https://x/openai/v1?k=v"


def test_does_not_override_already_set_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=fromfile\n", encoding="utf-8")
    target = {"A": "fromenv"}
    loaded = load_env_file(env_file, environ=target)
    assert loaded == 0  # the default: the existing (ambient) value wins
    assert target["A"] == "fromenv"


def test_override_makes_the_file_authoritative(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=fromfile\n", encoding="utf-8")
    target = {"A": "fromenv"}
    loaded = load_env_file(env_file, environ=target, override=True)
    assert loaded == 1  # the file value replaced the stale ambient one
    assert target["A"] == "fromfile"


def test_override_warns_only_on_a_real_conflict(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=fromfile\nB=same\nC=new\n", encoding="utf-8")
    target = {"A": "stale", "B": "same"}  # A conflicts, B matches, C is absent
    conflicts: list[str] = []
    load_env_file(env_file, environ=target, override=True, on_conflict=conflicts.append)
    assert conflicts == ["A"]  # only the differing ambient key is reported
    assert target == {"A": "fromfile", "B": "same", "C": "new"}


def test_no_conflict_callback_without_override(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=fromfile\n", encoding="utf-8")
    target = {"A": "stale"}
    conflicts: list[str] = []
    load_env_file(env_file, environ=target, on_conflict=conflicts.append)  # override defaults off
    assert conflicts == []  # the default never clobbers, so nothing to warn about
    assert target["A"] == "stale"


def test_missing_file_is_a_noop(tmp_path: Path) -> None:
    target: dict[str, str] = {}
    assert load_env_file(tmp_path / "nope.env", environ=target) == 0
    assert target == {}


def test_malformed_line_without_equals_is_skipped(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NOPE\nA=1\n", encoding="utf-8")
    target: dict[str, str] = {}
    assert load_env_file(env_file, environ=target) == 1
    assert target == {"A": "1"}
