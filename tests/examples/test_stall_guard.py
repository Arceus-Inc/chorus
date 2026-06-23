"""Regression: the standup demo's stall guard must not mistake a long single beat for a stall.

The run-13 bug: a contract-derived (per-module) decomposition funnels every module through one
foundation task, so exactly one engineer builds for minutes while every other child waits ``todo`` and
no status changes. The guard fired anyway — it ignored ``running_beats``. ``_progress_stalled`` is the
extracted decision: an actively-running beat is WORKING, never a stall.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_RUN = Path(__file__).resolve().parents[2] / "standup-app" / "run.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("standup_run", _RUN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_running_beat_is_never_a_stall_even_after_the_window() -> None:
    run = _load()
    # the run-13 case: one long beat, idle far past the window, but a beat IS running → NOT stalled
    assert run._progress_stalled(
        running_beats=1, idle_s=999.0, stall_after_s=200.0, has_children=True
    ) is False


def test_quiet_and_idle_past_the_window_is_a_stall() -> None:
    run = _load()
    # no beat running, no status change for longer than the window, children exist → genuinely stuck
    assert run._progress_stalled(
        running_beats=0, idle_s=201.0, stall_after_s=200.0, has_children=True
    ) is True


def test_within_the_window_is_not_a_stall() -> None:
    run = _load()
    assert run._progress_stalled(
        running_beats=0, idle_s=10.0, stall_after_s=200.0, has_children=True
    ) is False


def test_no_children_is_never_a_stall() -> None:
    run = _load()
    assert run._progress_stalled(
        running_beats=0, idle_s=999.0, stall_after_s=200.0, has_children=False
    ) is False
