"""The kernel's verify-runner — runs the reviewer-discovered command in the author's worktree.

Deterministic: real subprocesses (`true`/`false`/`echo`/`sleep`), no model. The exit code is the
objective floor; a timeout or spawn failure is a non-zero exit (a failing build).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.heartbeat._scheduler import _run_verify_command

pytestmark = pytest.mark.unit


def test_passing_command_returns_zero(tmp_path: Path) -> None:
    code, _ = _run_verify_command(tmp_path, "true", timeout_s=10)
    assert code == 0


def test_failing_command_returns_nonzero(tmp_path: Path) -> None:
    code, _ = _run_verify_command(tmp_path, "false", timeout_s=10)
    assert code != 0


def test_output_is_captured(tmp_path: Path) -> None:
    code, output = _run_verify_command(tmp_path, "echo hello-build", timeout_s=10)
    assert code == 0 and "hello-build" in output


def test_runs_in_the_worktree(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("inside-the-worktree", encoding="utf-8")
    code, output = _run_verify_command(tmp_path, "cat marker.txt", timeout_s=10)
    assert code == 0 and "inside-the-worktree" in output


def test_timeout_is_a_nonzero_exit(tmp_path: Path) -> None:
    code, output = _run_verify_command(tmp_path, "sleep 5", timeout_s=1)
    assert code != 0 and "timeout" in output.lower()
