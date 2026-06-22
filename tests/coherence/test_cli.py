"""`python -m chorus.coherence` — the integrate-gate command (spec 15 §4.3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "chorus.coherence", "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_clean_tree_exits_zero(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from pkg.core import Thing\n__all__ = ['Thing']\n")
    (tmp_path / "pkg" / "core.py").write_text("class Thing:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n- `pkg/core.py` — Thing\n"
        "## Public API\n- `pkg.Thing`\n## Ownership\n- `pkg/core.py` -> ada\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_agents_md_fails(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "agents_md_missing" in (result.stdout + result.stderr)


def test_split_brain_duplicate_fails(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from pkg.a import Trainer\n")
    (tmp_path / "pkg" / "a.py").write_text("class Trainer:\n    pass\n")
    (tmp_path / "pkg" / "b.py").write_text("class Trainer:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — e\n- `pkg/a.py` — a\n- `pkg/b.py` — b\n"
        "## Public API\n- `pkg.Trainer`\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "duplicate_symbol" in (result.stdout + result.stderr)


_PLACEHOLDER_MD = (
    "# AGENTS.md\n## Module map\n- `<package>/__init__.py` — entry\n"
    "## Public API\n- `<package>.<Symbol>`\n## Ownership\n- `<package>/<file>.py` -> <id>\n"
)


def test_placeholder_contract_over_coherent_code_passes(tmp_path: Path) -> None:
    # the live-run regression: the manager left AGENTS.md unfilled but the code is coherent + importable
    # — the gate must NOT block (it would be a spurious placeholder-mismatch block).
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from pkg.core import Thing\n__all__ = ['Thing']\n")
    (tmp_path / "pkg" / "core.py").write_text("class Thing:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(_PLACEHOLDER_MD)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unauthored" in (result.stdout + result.stderr)


def test_placeholder_contract_still_blocks_a_public_rival(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from pkg.a import Trainer\n")
    (tmp_path / "pkg" / "a.py").write_text("class Trainer:\n    pass\n")
    (tmp_path / "pkg" / "b.py").write_text("class Trainer:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(_PLACEHOLDER_MD)
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "duplicate_symbol" in (result.stdout + result.stderr)


_SCAFFOLD_ONLY_MD = "# AGENTS.md\n## Module map\n## Public API\n## Ownership\n"


def test_scaffold_only_tree_fails_no_deliverable(tmp_path: Path) -> None:
    # the vacuous-done hole: a tree with ONLY harness scaffolding (no real source) must NOT pass —
    # an empty deliverable is not "coherent", it is nothing. Stack-agnostic (catches Rust/npm too).
    (tmp_path / "AGENTS.md").write_text(_SCAFFOLD_ONLY_MD)
    (tmp_path / "README.md").write_text("# x\n")
    (tmp_path / "gate_check.py").write_text("print('gate')\n")
    (tmp_path / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
    (tmp_path / "plan-presence.md").write_text("plan\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "no_deliverable" in (result.stdout + result.stderr)


def test_real_deliverable_satisfies_the_floor(tmp_path: Path) -> None:
    # a real package present → the floor is satisfied (even with an unfilled contract).
    (tmp_path / "gate_check.py").write_text("print('gate')\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from pkg.core import Thing\n__all__=['Thing']\n")
    (tmp_path / "pkg" / "core.py").write_text("class Thing:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(_PLACEHOLDER_MD)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unimportable_package_fails(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("import nonexistent_dep_xyz\n")
    (tmp_path / "pkg" / "core.py").write_text("class Thing:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — e\n- `pkg/core.py` — Thing\n"
        "## Public API\n- `pkg.core.Thing`\n"
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "not_importable" in (result.stdout + result.stderr)
