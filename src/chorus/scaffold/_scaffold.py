"""Stack-detected project scaffolding (the manifest-as-module fix).

A deliverable's packaging manifest (``pyproject.toml`` / ``Cargo.toml`` / ``package.json`` / ``go.mod``)
is NOT a source module — no engineer builds it and coherence must not treat it as one. But a manager
routinely lists it in the AGENTS.md module map, which deadlocks: the contract-derive skips non-source
files, so nobody is assigned the manifest, and coherence then flags it absent forever (the prefrank
block). The kernel instead scaffolds the project once, before fan-out, with the stack's own idiomatic
``init`` command (``cargo init`` / ``go mod init`` / ``npm init``) — or, for Python, a minimal
``pyproject.toml`` (``uv init`` imposes a conflicting ``src/`` layout). The manifest then exists from the
start: coherence never deadlocks on it and the gate can install the deps declared in it.
"""

from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

# A manifest filename → the stack it identifies. A declared manifest names the stack unambiguously.
_MANIFEST_STACK: dict[str, str] = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "Cargo.toml": "rust",
    "package.json": "node",
    "go.mod": "go",
}

# stack → its one canonical manifest file (what ``scaffold_if_missing`` guarantees exists).
_STACK_MANIFEST: dict[str, str] = {
    "python": "pyproject.toml",
    "rust": "Cargo.toml",
    "node": "package.json",
    "go": "go.mod",
}

# A minimal, valid manifest per stack — the toolchain-independent fallback (and Python's only path, since
# ``uv init`` would scaffold a conflicting ``src/`` package). ``{name}`` is the project directory name.
_MINIMAL_MANIFEST: dict[str, str] = {
    "python": '[project]\nname = "{name}"\nversion = "0.1.0"\nrequires-python = ">=3.10"\ndependencies = []\n',
    "rust": '[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n',
    "node": '{{\n  "name": "{name}",\n  "version": "0.1.0"\n}}\n',
    "go": "module {name}\n\ngo 1.21\n",
}

# Keyword → stack for inferring the stack from the goal text when no manifest is declared. Ordered:
# the first stack whose keywords appear wins.
_GOAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rust", ("rust", "cargo", "crate")),
    ("go", ("go module", "go.mod", "golang")),
    ("node", ("npm", "package.json", "typescript", "node", "javascript")),
    ("python", ("python", "pyproject", "pytest", "pip ", "numpy")),
)


def detect_stack(goal: str, declared_modules: Iterable[str] = ()) -> str | None:
    """The deliverable's stack — from a declared manifest first, else inferred from the goal text.

    Returns ``None`` when nothing identifies a stack (the caller then skips scaffolding rather than guess).
    """
    for module in declared_modules:
        name = module.replace("\\", "/").rsplit("/", 1)[-1]
        if name in _MANIFEST_STACK:
            return _MANIFEST_STACK[name]
    text = goal.lower()
    for stack, keywords in _GOAL_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return stack
    return None


def scaffold_command(stack: str, *, module: str = "app") -> tuple[str, ...] | None:
    """The stack's idiomatic project-init command, or ``None`` when scaffolding writes the manifest
    directly (Python — ``uv init`` would impose a conflicting ``src/`` layout)."""
    if stack == "rust":
        return ("cargo", "init", "--lib", "--name", module)
    if stack == "go":
        return ("go", "mod", "init", module)
    if stack == "node":
        return ("npm", "init", "-y")
    return None


def scaffold_if_missing(
    repo: Path,
    *,
    goal: str = "",
    declared_modules: Iterable[str] = (),
    run: Callable[..., Any] = subprocess.run,
) -> str | None:
    """Ensure ``repo`` has the manifest for its detected stack; return the stack if it scaffolded, else
    ``None`` (unknown stack, or the manifest already exists). Best-effort: tries the idiomatic ``init``
    command, then falls back to a minimal manifest so the file ALWAYS exists regardless of toolchain.
    """
    stack = detect_stack(goal, declared_modules)
    if stack is None:
        return None
    manifest = _STACK_MANIFEST[stack]
    if (repo / manifest).is_file():
        return None  # idempotent — never clobber an authored manifest
    name = repo.name or "app"
    command = scaffold_command(stack, module=name)
    if command is not None:
        # toolchain absent / failed → the minimal-manifest fallback below still guarantees the manifest
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            run(list(command), cwd=str(repo), capture_output=True, text=True, timeout=60, check=False)
    if not (repo / manifest).is_file():
        (repo / manifest).write_text(_MINIMAL_MANIFEST[stack].format(name=name), encoding="utf-8")
    return stack


__all__ = ["detect_stack", "scaffold_command", "scaffold_if_missing"]
