"""The kernel's verify-runner — runs the reviewer-discovered command in the author's worktree.

Deterministic: real Python subprocesses, no model. The exit code is the
objective floor; a timeout or spawn failure is a non-zero exit (a failing build).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chorus.heartbeat._scheduler import _run_verify_command

pytestmark = pytest.mark.unit


def _python(source: str) -> str:
    return subprocess.list2cmdline([sys.executable, "-c", source])


def test_passing_command_returns_zero(tmp_path: Path) -> None:
    code, _ = _run_verify_command(tmp_path, _python("pass"), timeout_s=10)
    assert code == 0


def test_failing_command_returns_nonzero(tmp_path: Path) -> None:
    code, _ = _run_verify_command(tmp_path, _python("raise SystemExit(1)"), timeout_s=10)
    assert code != 0


def test_output_is_captured(tmp_path: Path) -> None:
    code, output = _run_verify_command(tmp_path, _python("print('hello-build')"), timeout_s=10)
    assert code == 0 and "hello-build" in output


def test_runs_in_the_worktree(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("inside-the-worktree", encoding="utf-8")
    code, output = _run_verify_command(
        tmp_path,
        _python("from pathlib import Path; print(Path('marker.txt').read_text())"),
        timeout_s=10,
    )
    assert code == 0 and "inside-the-worktree" in output


def test_timeout_is_a_nonzero_exit(tmp_path: Path) -> None:
    code, output = _run_verify_command(
        tmp_path, _python("import time; time.sleep(5)"), timeout_s=1
    )
    assert code != 0 and "timeout" in output.lower()
