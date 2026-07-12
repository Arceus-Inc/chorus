"""design_exemplar — the Designer's read-only exemplar fetcher (designer §08).

The tool returns ONE vendored real-world ``DESIGN.md`` from the design-md-exemplars library, which lives
in the chorus package (NOT the worktree) — so ``design_lint``'s worktree-confined ``read_file`` can't
reach it. These tests use an INJECTED references root (``DesignExemplarTool(references_root=…)``) so they
are hermetic and don't depend on the vendored tree, plus one integration check against the real library.
No keys, no model, no net — a pure deterministic file reader, exactly like ``design_lint``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus_tools._design_exemplar import (
    DesignExemplarInput,
    DesignExemplarTool,
    available_exemplars,
    exemplars_root,
)

pytestmark = pytest.mark.integration


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _run(tool: DesignExemplarTool, ctx: object, payload: dict[str, object]) -> object:
    return asyncio.run(tool.execute(payload, ctx))  # type: ignore[arg-type]


@pytest.fixture
def fake_library(tmp_path: Path) -> Path:
    """A tiny stand-in exemplar library: two companies with a DESIGN.md, one empty dir."""
    root = tmp_path / "awesome-design-md"
    (root / "linear.app").mkdir(parents=True)
    (root / "linear.app" / "DESIGN.md").write_text(
        "# Linear\nprecise, dark-first.\n", encoding="utf-8"
    )
    (root / "stripe").mkdir()
    (root / "stripe" / "DESIGN.md").write_text("# Stripe\ntrustworthy, dense.\n", encoding="utf-8")
    (root / "no-design").mkdir()  # a dir WITHOUT a DESIGN.md — must be excluded from the catalog
    (root / "no-design" / "README.md").write_text("nope\n", encoding="utf-8")
    return root


class TestAvailableExemplars:
    def test_lists_only_dirs_with_a_design_md_sorted(self, fake_library: Path) -> None:
        assert available_exemplars(fake_library) == ("linear.app", "stripe")

    def test_missing_root_is_empty(self, tmp_path: Path) -> None:
        assert available_exemplars(tmp_path / "does-not-exist") == ()


class TestInput:
    def test_company_defaults_to_empty(self) -> None:
        assert DesignExemplarInput().company == ""


class TestCatalog:
    def test_no_argument_returns_the_catalog(self, fake_library: Path, tmp_path: Path) -> None:
        result = _run(DesignExemplarTool(fake_library), _ctx(tmp_path), {})
        assert result.is_error is False
        assert "linear.app" in result.content
        assert "stripe" in result.content
        assert result.metadata["artifacts"]["exemplars"] == ["linear.app", "stripe"]

    def test_empty_string_returns_the_catalog(self, fake_library: Path, tmp_path: Path) -> None:
        result = _run(DesignExemplarTool(fake_library), _ctx(tmp_path), {"company": "   "})
        assert result.is_error is False
        assert "Available exemplars (2)" in result.content

    def test_missing_library_is_an_error(self, tmp_path: Path) -> None:
        result = _run(DesignExemplarTool(tmp_path / "gone"), _ctx(tmp_path), {})
        assert result.is_error is True
        assert "root_cause" in result.metadata


class TestFetch:
    def test_valid_slug_returns_its_design_md(self, fake_library: Path, tmp_path: Path) -> None:
        result = _run(DesignExemplarTool(fake_library), _ctx(tmp_path), {"company": "linear.app"})
        assert result.is_error is False
        assert "precise, dark-first." in result.content
        assert result.metadata["status"] == "success"
        assert result.metadata["artifacts"]["company"] == "linear.app"

    def test_slug_is_case_insensitive_and_trimmed(self, fake_library: Path, tmp_path: Path) -> None:
        result = _run(DesignExemplarTool(fake_library), _ctx(tmp_path), {"company": "  STRIPE  "})
        assert result.is_error is False
        assert "trustworthy, dense." in result.content

    def test_unknown_slug_errors_with_suggestions_and_list(
        self, fake_library: Path, tmp_path: Path
    ) -> None:
        result = _run(DesignExemplarTool(fake_library), _ctx(tmp_path), {"company": "linaer"})
        assert result.is_error is True
        assert "linear.app" in result.content  # difflib close-match suggestion
        assert result.metadata["root_cause"].startswith("unknown exemplar")


class TestVendoredLibrary:
    """One check against the REAL vendored tree so a broken package path is caught."""

    def test_real_library_has_the_canonical_exemplars(self) -> None:
        root = exemplars_root()
        if not root.is_dir():
            pytest.skip("vendored exemplar library not present in this build")
        names = available_exemplars(root)
        assert len(names) >= 50
        for expected in ("stripe", "linear.app", "vercel", "notion"):
            assert expected in names

    def test_default_tool_reads_a_real_exemplar(self, tmp_path: Path) -> None:
        if not exemplars_root().is_dir():
            pytest.skip("vendored exemplar library not present in this build")
        result = _run(DesignExemplarTool(), _ctx(tmp_path), {"company": "stripe"})
        assert result.is_error is False
        assert result.metadata["artifacts"]["company"] == "stripe"
