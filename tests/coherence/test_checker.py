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


def test_tests_and_entry_points_are_not_orphans_or_missing(tmp_path: Path) -> None:
    # A complete library with a CLI entry point + test files is coherent: test files are discovered
    # (never imported), and a CLI is run (never imported) — neither is dead code. Tests also aren't part
    # of the SOURCE contract, so a declared-but-absent test file is not a missing-module violation.
    root = _pkg(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.core import Thing\n__all__ = ['Thing']\n",
            "pkg/core.py": "class Thing:\n    pass\n",
            "pkg/cli.py": "from pkg.core import Thing\n\ndef main() -> None:\n    print(Thing())\n",
            "pkg/__main__.py": "from pkg.cli import main\n\nif __name__ == '__main__':\n    main()\n",
            "tests/test_core.py": "from pkg import Thing\n\ndef test_thing():\n    assert Thing()\n",
        },
    )
    doc = AgentsMd(
        modules=(
            "pkg/__init__.py", "pkg/core.py", "pkg/cli.py", "pkg/__main__.py",
            "tests/test_core.py", "tests/test_absent.py",  # declared-but-absent test → not flagged
        ),
        public_api=("pkg.Thing",),
    )
    assert check_coherence(root, doc) == []


# --- placeholder-aware behaviour (spec 15): when the manager left AGENTS.md unfilled, the declared
# checks (missing_module/export, orphan) can't run, but the STRUCTURAL split-brain checks still do.

_PLACEHOLDER = AgentsMd(modules=("<package>/__init__.py",), public_api=("<package>.<Symbol>",))


def test_placeholder_contract_skips_declared_checks_on_coherent_code(tmp_path: Path) -> None:
    # a clean, coherent package + an UNFILLED contract must NOT produce a spurious block.
    root = _pkg(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.core import Thing\n__all__ = ['Thing']\n",
            "pkg/core.py": "class Thing:\n    pass\n",
        },
    )
    assert check_coherence(root, _PLACEHOLDER) == []


def test_placeholder_contract_still_catches_a_public_rival(tmp_path: Path) -> None:
    # two rival Trainers where __init__ re-exports Trainer — a real split brain, caught WITHOUT a contract.
    root = _pkg(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.a import Trainer\n",
            "pkg/a.py": "class Trainer:\n    pass\n",
            "pkg/b.py": "class Trainer:\n    pass\n",
        },
    )
    assert "duplicate_symbol" in [v.code for v in check_coherence(root, _PLACEHOLDER)]


def test_placeholder_ignores_internal_name_collisions(tmp_path: Path) -> None:
    # two modules each with a private/internal `Config` NOT re-exported by __init__ is not a public rival.
    root = _pkg(
        tmp_path,
        {
            "pkg/__init__.py": "from pkg.core import Thing\n",
            "pkg/core.py": "class Thing:\n    pass\nclass Config:\n    pass\n",
            "pkg/util.py": "class Config:\n    pass\n",  # not exported by __init__
        },
    )
    assert check_coherence(root, _PLACEHOLDER) == []
