"""Project scaffolding — lay down the stack's manifest at decompose so it is never a 'module'.

A manager that declares ``pyproject.toml`` / ``Cargo.toml`` in the AGENTS.md module map creates a
deadlock: the contract-derive only makes tasks for source modules, so nobody builds the manifest, and
coherence then flags it absent forever (the prefrank block). The kernel instead scaffolds the project
once — the stack's own ``init`` command (``cargo init`` / ``go mod init`` / ``npm init`` / a minimal
``pyproject.toml``) — so the manifest exists from the start and the gate can install declared deps.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chorus.scaffold import detect_stack, scaffold_command, scaffold_if_missing

pytestmark = pytest.mark.unit


def test_detect_stack_from_a_declared_manifest_module() -> None:
    # a manifest in the module map names the stack unambiguously
    assert detect_stack("Build a library", ("pyproject.toml", "pkg/__init__.py")) == "python"
    assert detect_stack("Build a crate", ("Cargo.toml", "src/lib.rs")) == "rust"
    assert detect_stack("Build it", ("package.json", "src/index.ts")) == "node"
    assert detect_stack("Build it", ("go.mod", "main.go")) == "go"


def test_detect_stack_falls_back_to_goal_keywords() -> None:
    assert detect_stack("Build a Rust crate `tinyvec` with cargo test", ()) == "rust"
    assert detect_stack("Build a Go module with go.mod", ()) == "go"
    assert detect_stack("Ship an npm package in TypeScript", ()) == "node"
    assert detect_stack("Build a Python library, tests with pytest", ()) == "python"


def test_detect_stack_is_none_when_ambiguous() -> None:
    assert detect_stack("Build a thing", ()) is None


def test_scaffold_command_is_the_stacks_idiomatic_init() -> None:
    assert scaffold_command("rust", module="tinyvec") == ("cargo", "init", "--lib", "--name", "tinyvec")
    assert scaffold_command("go", module="tinyvec") == ("go", "mod", "init", "tinyvec")
    assert scaffold_command("node", module="app") == ("npm", "init", "-y")
    # python is scaffolded by writing a minimal manifest (uv init imposes a conflicting src/ layout)
    assert scaffold_command("python", module="app") is None


def test_scaffold_if_missing_writes_a_python_manifest(tmp_path: Path) -> None:
    stack = scaffold_if_missing(tmp_path, goal="Build a python library", declared_modules=("pyproject.toml",))
    assert stack == "python"
    assert (tmp_path / "pyproject.toml").is_file()
    assert "[project]" in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_scaffold_if_missing_is_idempotent_and_never_clobbers(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'real'\ndependencies = ['numpy']\n", encoding="utf-8")
    stack = scaffold_if_missing(tmp_path, goal="python", declared_modules=("pyproject.toml",))
    assert stack is None  # already present → no-op
    assert "numpy" in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")  # the real one is kept


def test_scaffold_if_missing_falls_back_to_a_minimal_manifest_when_the_toolchain_is_absent(
    tmp_path: Path,
) -> None:
    # `cargo` may not be installed; the init command is best-effort and falls back to a minimal manifest
    # so the manifest ALWAYS exists (coherence never deadlocks on it), regardless of the run environment.
    def _no_toolchain(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("cargo not installed")

    stack = scaffold_if_missing(
        tmp_path, goal="Build a Rust crate", declared_modules=("Cargo.toml",), run=_no_toolchain
    )
    assert stack == "rust"
    assert (tmp_path / "Cargo.toml").is_file()
    assert "[package]" in (tmp_path / "Cargo.toml").read_text(encoding="utf-8")


def test_scaffold_if_missing_returns_none_for_an_undetectable_stack(tmp_path: Path) -> None:
    assert scaffold_if_missing(tmp_path, goal="Build a thing", declared_modules=()) is None
