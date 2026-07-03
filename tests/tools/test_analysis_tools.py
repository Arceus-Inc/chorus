"""Unit tests for the Analyst's analysis tools (warehouse_query / repo_search / notebook_run / chart_render)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from dream.tools._context import ToolExecutionContext

from chorus_tools import (
    ChartRenderTool,
    NotebookRunTool,
    RepoSearchTool,
    WarehouseQueryTool,
    analysis_tool,
)

pytestmark = pytest.mark.unit


def _ctx(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=tmp_path, session_id="s-test")


def _run(coro):
    return asyncio.run(coro)


def _seed_warehouse(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "warehouse.db")
    conn.execute("CREATE TABLE sales (region TEXT, month TEXT, revenue INTEGER)")
    conn.executemany(
        "INSERT INTO sales VALUES (?, ?, ?)",
        [("west", "Jan", 100), ("west", "Feb", 150), ("east", "Jan", 80), ("east", "Feb", 60)],
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- warehouse_query


def test_warehouse_query_returns_rows(tmp_path: Path) -> None:
    _seed_warehouse(tmp_path)
    res = _run(
        WarehouseQueryTool().execute(
            {"sql": "SELECT region, SUM(revenue) AS total FROM sales GROUP BY region ORDER BY region"},
            _ctx(tmp_path),
        )
    )
    assert not res.is_error
    assert "east" in res.content and "west" in res.content
    assert "140" in res.content and "250" in res.content  # east 80+60, west 100+150


def test_warehouse_query_rejects_writes(tmp_path: Path) -> None:
    _seed_warehouse(tmp_path)
    res = _run(WarehouseQueryTool().execute({"sql": "DELETE FROM sales"}, _ctx(tmp_path)))
    assert res.is_error and "read-only" in res.content


def test_warehouse_query_missing_db_is_a_clean_error(tmp_path: Path) -> None:
    res = _run(WarehouseQueryTool().execute({"sql": "SELECT 1"}, _ctx(tmp_path)))
    assert res.is_error and "no warehouse" in res.content


def test_warehouse_query_is_read_only() -> None:
    assert WarehouseQueryTool().is_read_only_for({"sql": "SELECT 1"}) is True


# --------------------------------------------------------------------------- repo_search


def test_repo_search_finds_matches(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world\nchurn rate is high\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1  # churn\n", encoding="utf-8")
    res = _run(RepoSearchTool().execute({"query": r"churn"}, _ctx(tmp_path)))
    assert not res.is_error
    assert "a.txt:2" in res.content and "b.py:1" in res.content


def test_repo_search_no_match(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("nothing here\n", encoding="utf-8")
    res = _run(RepoSearchTool().execute({"query": r"zzz"}, _ctx(tmp_path)))
    assert "(no matches)" in res.content


def test_repo_search_skips_dot_dirs(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret churn token\n", encoding="utf-8")
    (tmp_path / "real.txt").write_text("churn here\n", encoding="utf-8")
    res = _run(RepoSearchTool().execute({"query": r"churn"}, _ctx(tmp_path)))
    assert "real.txt" in res.content and ".git" not in res.content


# --------------------------------------------------------------------------- notebook_run


def test_notebook_run_executes_and_prints(tmp_path: Path) -> None:
    res = _run(NotebookRunTool().execute({"code": "print(2 + 2)"}, _ctx(tmp_path)))
    assert not res.is_error and "4" in res.content


def test_notebook_run_state_persists_across_cells(tmp_path: Path) -> None:
    tool = NotebookRunTool()
    _run(tool.execute({"code": "x = 21"}, _ctx(tmp_path)))
    res = _run(tool.execute({"code": "print(x * 2)"}, _ctx(tmp_path)))
    assert not res.is_error and "42" in res.content


def test_notebook_run_reports_errors(tmp_path: Path) -> None:
    res = _run(NotebookRunTool().execute({"code": "raise ValueError('boom')"}, _ctx(tmp_path)))
    assert res.is_error and "boom" in res.content


def test_notebook_run_has_pandas(tmp_path: Path) -> None:
    res = _run(
        NotebookRunTool().execute(
            {"code": "import pandas as pd; print(pd.DataFrame({'a':[1,2,3]})['a'].sum())"},
            _ctx(tmp_path),
        )
    )
    assert not res.is_error and "6" in res.content


# --------------------------------------------------------------------------- chart_render


def test_chart_render_writes_png(tmp_path: Path) -> None:
    (tmp_path / "d.csv").write_text("x,y\n1,10\n2,20\n3,15\n", encoding="utf-8")
    res = _run(
        ChartRenderTool().execute(
            {"data": "d.csv", "kind": "line", "x": "x", "y": "y", "output": "out.png"}, _ctx(tmp_path)
        )
    )
    assert not res.is_error, res.content
    assert (tmp_path / "out.png").is_file() and (tmp_path / "out.png").stat().st_size > 0


def test_chart_render_rejects_unknown_kind(tmp_path: Path) -> None:
    (tmp_path / "d.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    res = _run(ChartRenderTool().execute({"data": "d.csv", "kind": "pie", "x": "x", "y": "y"}, _ctx(tmp_path)))
    assert res.is_error and "unknown chart kind" in res.content


# --------------------------------------------------------------------------- registry helper


def test_analysis_tool_resolves_known_names() -> None:
    assert isinstance(analysis_tool("warehouse_query"), WarehouseQueryTool)
    assert isinstance(analysis_tool("repo_search"), RepoSearchTool)
    assert isinstance(analysis_tool("notebook_run"), NotebookRunTool)
    assert isinstance(analysis_tool("chart_render"), ChartRenderTool)
    assert analysis_tool("not_a_tool") is None
