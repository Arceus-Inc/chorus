"""Deterministic coherence checks reconciled to AGENTS.md (spec 15 §4.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.coherence import AgentsMd, check_coherence

pytestmark = pytest.mark.unit


def _pkg(tmp: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    root = _pkg(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.core import Thing\n__all__ = ['Thing']\n",
            "pkg/core.py": "class Thing:\n    pass\n",
        },
    )
    doc = AgentsMd(
        modules=("pkg/__init__.py", "pkg/core.py"),
        public_api=("pkg.Thing",),
        ownership={"pkg/core.py": "ada"},
    )
    assert check_coherence(root, doc) == []


def test_missing_declared_module(tmp_path: Path) -> None:
    root = _pkg(tmp_path, {"pkg/__init__.py": "\n"})
    doc = AgentsMd(modules=("pkg/__init__.py", "pkg/core.py"))
    assert "missing_module" in [v.code for v in check_coherence(root, doc)]


def test_duplicate_public_symbol(tmp_path: Path) -> None:
    root = _pkg(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.a import Trainer\n",
            "pkg/a.py": "class Trainer:\n    pass\n",
            "pkg/b.py": "class Trainer:\n    pass\n",  # rival definition
        },
    )
    doc = AgentsMd(
        modules=("pkg/__init__.py", "pkg/a.py", "pkg/b.py"), public_api=("pkg.Trainer",)
    )
    assert "duplicate_symbol" in [v.code for v in check_coherence(root, doc)]


def test_init_missing_a_declared_export(tmp_path: Path) -> None:
    root = _pkg(
        tmp_path,
        {"pkg/__init__.py": "\n", "pkg/core.py": "class Thing:\n    pass\n"},  # exports nothing
    )
    doc = AgentsMd(modules=("pkg/__init__.py", "pkg/core.py"), public_api=("pkg.Thing",))
    assert "missing_export" in [v.code for v in check_coherence(root, doc)]


def test_orphan_module(tmp_path: Path) -> None:
    root = _pkg(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.core import Thing\n",
            "pkg/core.py": "class Thing:\n    pass\n",
            "pkg/dead.py": "X = 1\n",  # imported by nobody
        },
    )
    doc = AgentsMd(
        modules=("pkg/__init__.py", "pkg/core.py", "pkg/dead.py"), public_api=("pkg.Thing",)
    )
    assert "orphan_module" in [v.code for v in check_coherence(root, doc)]
