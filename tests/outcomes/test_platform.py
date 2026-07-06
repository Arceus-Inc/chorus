"""Cross-platform DoD command building + runtime brief block (chorus.outcomes._platform).

The round-trip tests are the ones that matter: they run the generated command through the *real* shell
(``cmd.exe`` on Windows, ``/bin/sh`` on POSIX) exactly as dream's ``create_subprocess_shell`` oracle
does, proving the floor passes on the host it was authored on — the guarantee POSIX ``test``/``grep``
floors could not make.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chorus.outcomes import (
    PlatformInfo,
    detect_platform,
    file_exists,
    file_matches,
    file_matches_any,
    glob_at_least,
    min_words,
    python_check,
    runtime_brief_block,
)

pytestmark = pytest.mark.unit


def _run(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``command`` through the OS shell exactly as dream's oracle does (``shell=True``)."""
    return subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, check=False)


# --- command shape -------------------------------------------------------------------------------


def test_command_is_a_python_c_invocation_with_no_leaked_shell_metacharacters() -> None:
    command = python_check(
        [file_exists("app.js"), file_matches("app.js", "addEventListener", label="wiring")]
    )
    assert " -c " in command
    assert "import base64" in command
    # The check details (paths, regexes) must be encoded in the base64 blob, never in cleartext where a
    # shell could reinterpret them.
    assert "addEventListener" not in command
    assert "app.js" not in command


def test_explicit_interpreter_is_honoured() -> None:
    assert python_check([file_exists("x")], python="python").startswith("python -c ")


def test_interpreter_with_spaces_is_quoted() -> None:
    command = python_check([file_exists("x")], python=r"C:\Program Files\Python\python.exe")
    assert command.startswith('"C:\\Program Files\\Python\\python.exe" -c ')


# --- round trips through the real shell ----------------------------------------------------------


def test_all_checks_pass_exits_zero(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text(
        "// a real module\n" + "document.addEventListener('click', () => {});\n" + "word " * 200,
        encoding="utf-8",
    )
    command = python_check(
        [
            file_exists("app.js"),
            min_words("app.js", 150),
            file_matches("app.js", r"addEventListener", label="event wiring"),
        ]
    )
    result = _run(command, tmp_path)
    assert result.returncode == 0, result.stderr


def test_missing_file_fails_with_readable_reason(tmp_path: Path) -> None:
    result = _run(python_check([file_exists("nope.js")]), tmp_path)
    assert result.returncode != 0
    assert "DoD FAIL" in result.stderr
    assert "nope.js" in result.stderr


def test_empty_file_fails(tmp_path: Path) -> None:
    (tmp_path / "empty.js").write_text("", encoding="utf-8")
    assert _run(python_check([file_exists("empty.js")]), tmp_path).returncode != 0


def test_min_words_below_threshold_fails(tmp_path: Path) -> None:
    (tmp_path / "thin.md").write_text("only three words", encoding="utf-8")
    result = _run(python_check([min_words("thin.md", 150)]), tmp_path)
    assert result.returncode != 0
    assert "words" in result.stderr


def test_regex_absent_fails(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("const x = 1;\n" + "word " * 200, encoding="utf-8")
    result = _run(
        python_check([file_matches("app.js", r"addEventListener", label="event wiring")]), tmp_path
    )
    assert result.returncode != 0
    assert "event wiring" in result.stderr


def test_regex_present_passes(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("btn.addEventListener('click', run);\n", encoding="utf-8")
    assert (
        _run(
            python_check([file_matches("app.js", r"addEventListener", label="wiring")]), tmp_path
        ).returncode
        == 0
    )


def test_matches_any_passes_when_one_matches(tmp_path: Path) -> None:
    (tmp_path / "test.js").write_text("import { test } from 'node:test';\n", encoding="utf-8")
    command = python_check(
        [
            file_matches_any(
                "test.js", [r"node:test", r"vitest", r"@playwright/test"], label="a test runner"
            )
        ]
    )
    assert _run(command, tmp_path).returncode == 0


def test_matches_any_fails_when_none_match(tmp_path: Path) -> None:
    (tmp_path / "test.js").write_text("console.log('nothing here');\n", encoding="utf-8")
    command = python_check(
        [
            file_matches_any(
                "test.js", [r"node:test", r"vitest", r"@playwright/test"], label="a test runner"
            )
        ]
    )
    assert _run(command, tmp_path).returncode != 0


def test_glob_at_least_counts_matching_files(tmp_path: Path) -> None:
    (tmp_path / "test-results").mkdir()
    (tmp_path / "test-results" / "a.png").write_text("x", encoding="utf-8")
    (tmp_path / "test-results" / "b.png").write_text("y", encoding="utf-8")
    assert _run(python_check([glob_at_least("test-results/**/*.png", 2)]), tmp_path).returncode == 0
    assert _run(python_check([glob_at_least("test-results/**/*.png", 3)]), tmp_path).returncode != 0


def test_regex_with_shell_special_characters_survives_the_shell(tmp_path: Path) -> None:
    # A regex full of characters cmd.exe/sh treat specially (^, &, |, %, <, >, quotes) must still be
    # evaluated by Python, not the shell — the base64 envelope guarantees it.
    (tmp_path / "weird.txt").write_text("start & pipe | pct % lt < gt > done\n", encoding="utf-8")
    command = python_check(
        [file_matches("weird.txt", r"^start & pipe \| pct % lt < gt > done$", label="tricky")]
    )
    assert _run(command, tmp_path).returncode == 0


# --- detection + brief block ---------------------------------------------------------------------


def test_detect_platform_reports_a_shell_matching_the_os() -> None:
    info = detect_platform()
    assert isinstance(info, PlatformInfo)
    assert info.python_version.count(".") >= 2
    import sys

    if sys.platform == "win32":
        assert info.shell.lower().endswith("cmd.exe") or "cmd" in info.shell.lower()
    else:
        assert info.shell == "/bin/sh"


def test_runtime_brief_block_states_platform_agnostic_dod() -> None:
    block = runtime_brief_block(
        PlatformInfo(
            os_name="Windows",
            os_release="11",
            shell="C:\\WINDOWS\\system32\\cmd.exe",
            python_version="3.11.9",
            node_version="v22.19.0",
            npm_version="10.9.3",
            playwright_browsers_cached=True,
        )
    )
    assert "Operating environment" in block
    assert "Windows" in block
    assert "cmd.exe" in block
    assert "Node.js v22.19.0" in block
    assert "platform-agnostic Python check" in block
    assert "cached" in block


def test_runtime_brief_block_flags_missing_runtimes() -> None:
    block = runtime_brief_block(
        PlatformInfo(
            os_name="Linux",
            os_release="6.1",
            shell="/bin/sh",
            python_version="3.11.9",
            node_version=None,
            npm_version=None,
            playwright_browsers_cached=False,
        )
    )
    assert "Node.js: not on PATH" in block
    assert "not cached" in block
