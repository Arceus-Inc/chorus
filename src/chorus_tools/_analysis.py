"""Analyst analysis tools — model-callable dream ``BaseTool``s for local data work.

These are the Analyst's real instruments, implemented locally (no external services): a read-only SQL
warehouse over a SQLite file, a stateful notebook executor, a declarative chart renderer, and a
worktree-confined repo search. Each is a dream ``BaseTool`` so the model can call it directly and the
permission gate / tier system applies; ``chorus_harness`` registers them into a role's registry when
the role lists the tool name.

Compute tools (``notebook_run`` / ``chart_render``) spawn **this process's interpreter**
(``sys.executable`` — the chorus venv, which carries pandas/numpy/matplotlib), so the scientific stack
is always available regardless of the worktree's ``PATH``. Read tools (``warehouse_query`` /
``repo_search``) run in-process and never mutate anything.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from typing import Any

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration, ToolEffects
from dream.tools._context import ToolExecutionContext
from dream.tools._paths import PathEscapesRoot, resolve_within
from pydantic import BaseModel, Field

__all__ = [
    "ChartRenderInput",
    "ChartRenderTool",
    "NotebookRunInput",
    "NotebookRunTool",
    "RepoSearchInput",
    "RepoSearchTool",
    "WarehouseQueryInput",
    "WarehouseQueryTool",
    "analysis_tool",
]

_NOTEBOOK_DIR = ".analysis"
_NOTEBOOK_CELLS = "notebook_cells.py"
_NOTEBOOK_RUNNER = "_notebook_run.py"
_OUTPUT_CAP = 12_000


def _cap(text: str, limit: int = _OUTPUT_CAP) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


# --------------------------------------------------------------------------- warehouse_query


class WarehouseQueryInput(BaseModel):
    """Arguments for ``warehouse_query`` — a read-only SQL query over the local warehouse."""

    sql: str = Field(description="A single read-only SQL statement (SELECT / WITH / PRAGMA / EXPLAIN).")
    database: str = Field(
        default="warehouse.db",
        description="SQLite database file in the working directory (default 'warehouse.db').",
    )
    max_rows: int = Field(default=200, ge=1, le=5000, description="Row cap on the result set.")


_READ_ONLY_SQL_HEADS = ("select", "with", "pragma", "explain")


class WarehouseQueryTool(BaseTool):
    """Run a read-only SQL query against the local SQLite warehouse and return rows as a table."""

    name = "warehouse_query"
    description = (
        "Query the local SQL data warehouse (a SQLite database) with a single read-only statement "
        "(SELECT/WITH/PRAGMA/EXPLAIN). Use `PRAGMA table_info(<table>)` or "
        "`SELECT name FROM sqlite_master WHERE type='table'` to discover the schema first. Returns the "
        "result rows as a text table; writes are rejected."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=30.0)
    input_model = WarehouseQueryInput

    def is_read_only_for(self, input: dict[str, Any]) -> bool:
        return True

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = WarehouseQueryInput.model_validate(input)
        head = args.sql.lstrip().split(None, 1)[0].lower() if args.sql.strip() else ""
        if head not in _READ_ONLY_SQL_HEADS:
            return ToolResult(
                content=(
                    f"refused: warehouse_query is read-only; statement must start with one of "
                    f"{_READ_ONLY_SQL_HEADS}, got {head!r}"
                ),
                is_error=True,
                metadata={"root_cause": "non-read-only-sql", "stop_condition": "rewrite as a SELECT"},
            )
        try:
            db_path = resolve_within(ctx.working_dir, args.database)
        except PathEscapesRoot:
            return ToolResult(content=f"refused: database path escapes the worktree: {args.database}", is_error=True)
        if not db_path.is_file():
            return ToolResult(
                content=f"no warehouse found at {args.database!r} in the working directory",
                is_error=True,
                metadata={"safe_retry": "check the database filename or list files first"},
            )
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            return ToolResult(content=f"could not open warehouse: {exc}", is_error=True)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(args.sql)
            rows = cursor.fetchmany(args.max_rows)
            cols = [d[0] for d in cursor.description] if cursor.description else []
        except sqlite3.Error as exc:
            return ToolResult(
                content=f"SQL error: {exc}",
                is_error=True,
                metadata={"root_cause": "sql-error", "safe_retry": "fix the SQL and retry"},
            )
        finally:
            conn.close()
        if not cols:
            return ToolResult(content="(statement ran; no result columns)", metadata={"rows": 0})
        body = _render_table(cols, rows)
        more = "" if len(rows) < args.max_rows else f"\n(row cap {args.max_rows} reached; refine the query)"
        return ToolResult(content=_cap(body + more), metadata={"rows": len(rows), "columns": cols})


def _render_table(cols: list[str], rows: list[sqlite3.Row]) -> str:
    widths = [len(c) for c in cols]
    str_rows: list[list[str]] = []
    for row in rows:
        cells = ["" if row[i] is None else str(row[i]) for i in range(len(cols))]
        str_rows.append(cells)
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    sep = "-+-".join("-" * widths[i] for i in range(len(cols)))
    lines = [header, sep]
    lines.extend(" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)) for r in str_rows)
    return "\n".join(lines)


# --------------------------------------------------------------------------- repo_search


class RepoSearchInput(BaseModel):
    """Arguments for ``repo_search`` — a worktree-confined text/regex search."""

    query: str = Field(description="A regular expression to search for across files.")
    glob: str = Field(default="**/*", description="Glob of files to search, relative to the worktree.")
    max_results: int = Field(default=50, ge=1, le=500, description="Cap on the number of matches returned.")


_SKIP_DIRS = {".git", ".dream", ".analysis", ".harness", "node_modules", "__pycache__", ".venv"}
_MAX_FILE_BYTES = 2_000_000


class RepoSearchTool(BaseTool):
    """Search the working directory's files for a regex and return file:line:text matches."""

    name = "repo_search"
    description = (
        "Search the files in your working directory for a regular expression. Returns matching "
        "file:line:text lines. Confined to the worktree; read-only. Use it to locate data files, "
        "columns, or prior notes before analysing."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=30.0)
    input_model = RepoSearchInput

    def is_read_only_for(self, input: dict[str, Any]) -> bool:
        return True

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = RepoSearchInput.model_validate(input)
        try:
            pattern = re.compile(args.query)
        except re.error as exc:
            return ToolResult(content=f"invalid regex: {exc}", is_error=True)
        root = ctx.working_dir
        matches: list[str] = []
        for path in sorted(root.glob(args.glob)):
            if not path.is_file() or any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue  # skip binary / unreadable
            rel = path.relative_to(root).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                    if len(matches) >= args.max_results:
                        body = "\n".join(matches) + f"\n(stopped at {args.max_results} matches)"
                        return ToolResult(content=_cap(body), metadata={"matches": len(matches)})
        if not matches:
            return ToolResult(content="(no matches)", metadata={"matches": 0})
        return ToolResult(content=_cap("\n".join(matches)), metadata={"matches": len(matches)})


# --------------------------------------------------------------------------- notebook_run


class NotebookRunInput(BaseModel):
    """Arguments for ``notebook_run`` — execute a Python cell in the persistent analysis notebook."""

    code: str = Field(description="Python source for this cell. State persists across cells in the beat.")
    reset: bool = Field(default=False, description="Clear all prior cells before running this one.")


class NotebookRunTool(BaseTool):
    """Run a Python cell in a stateful notebook (pandas/numpy available); returns the cell's output.

    Cells accumulate in the worktree; each call re-executes the whole notebook in one process so
    variables defined in earlier cells are in scope, then returns stdout/stderr from the run. This is
    the Analyst's primary compute surface — prefer it over ad-hoc shell for analysis.
    """

    name = "notebook_run"
    description = (
        "Execute a Python cell in your persistent analysis notebook. pandas, numpy and matplotlib are "
        "available. Variables from earlier cells stay in scope (the notebook re-runs in one process). "
        "`print(...)` the values you need to see; they are returned to you. Pass reset=true to start a "
        "fresh notebook. Prefer this over the shell for computation."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=120.0)
    input_model = NotebookRunInput

    def effects_for(self, input: dict[str, Any]) -> ToolEffects:
        # It executes Python; classify like a command so the gate anchors it to the worktree.
        return ToolEffects(command="python notebook_run")

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = NotebookRunInput.model_validate(input)
        nb_dir = ctx.working_dir / _NOTEBOOK_DIR
        nb_dir.mkdir(parents=True, exist_ok=True)
        cells_path = nb_dir / _NOTEBOOK_CELLS
        prior = "" if args.reset or not cells_path.is_file() else cells_path.read_text(encoding="utf-8")
        cell_header = f"\n\n# ---- cell {prior.count('# ---- cell') + 1} ----\n"
        notebook_src = (prior + cell_header + args.code).lstrip("\n")
        cells_path.write_text(notebook_src, encoding="utf-8")
        runner = nb_dir / _NOTEBOOK_RUNNER
        runner.write_text(notebook_src, encoding="utf-8")
        result = await ctx.run_subprocess(
            [sys.executable, str(runner)], cwd=ctx.working_dir, timeout=self.declaration.timeout_seconds
        )
        rc = result.metadata.get("returncode")
        if rc not in (0, None):
            return ToolResult(
                content=_cap(f"notebook cell failed (exit {rc}):\n{result.content}"),
                is_error=True,
                metadata={"root_cause": "notebook-cell-error", "safe_retry": "fix the cell and re-run"},
            )
        out = result.content.strip() or "(cell ran; no output — remember to print() what you need)"
        return ToolResult(content=_cap(out), metadata={"cells": notebook_src.count("# ---- cell")})


# --------------------------------------------------------------------------- chart_render


class ChartRenderInput(BaseModel):
    """Arguments for ``chart_render`` — render a chart from a CSV to a PNG."""

    data: str = Field(description="CSV file in the working directory to plot.")
    kind: str = Field(default="line", description="Chart kind: line | bar | scatter | hist.")
    x: str = Field(default="", description="Column for the x axis (omit for hist).")
    y: str = Field(default="", description="Column(s) for the y axis, comma-separated (omit for hist).")
    title: str = Field(default="", description="Chart title.")
    output: str = Field(default="chart.png", description="Output PNG path in the working directory.")


_CHART_KINDS = {"line", "bar", "scatter", "hist"}


class ChartRenderTool(BaseTool):
    """Render a chart (line/bar/scatter/hist) from a CSV to a PNG file in the worktree."""

    name = "chart_render"
    description = (
        "Render a chart from a CSV file to a PNG in your working directory. kind is one of "
        "line/bar/scatter/hist; give the x and y column names (y may be comma-separated; omit both for "
        "a histogram). Returns the saved PNG path. Use it to visualise a finding."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=60.0)
    input_model = ChartRenderInput

    def effects_for(self, input: dict[str, Any]) -> ToolEffects:
        return ToolEffects(command="python chart_render")

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = ChartRenderInput.model_validate(input)
        if args.kind not in _CHART_KINDS:
            return ToolResult(content=f"unknown chart kind {args.kind!r}; use one of {sorted(_CHART_KINDS)}", is_error=True)
        try:
            resolve_within(ctx.working_dir, args.data)
            resolve_within(ctx.working_dir, args.output)
        except PathEscapesRoot:
            return ToolResult(content="refused: data/output path escapes the worktree", is_error=True)
        ys = [c.strip() for c in args.y.split(",") if c.strip()]
        script = _chart_script(data=args.data, kind=args.kind, x=args.x, ys=ys, title=args.title, output=args.output)
        nb_dir = ctx.working_dir / _NOTEBOOK_DIR
        nb_dir.mkdir(parents=True, exist_ok=True)
        script_path = nb_dir / "_chart.py"
        script_path.write_text(script, encoding="utf-8")
        result = await ctx.run_subprocess(
            [sys.executable, str(script_path)], cwd=ctx.working_dir, timeout=self.declaration.timeout_seconds
        )
        rc = result.metadata.get("returncode")
        if rc not in (0, None):
            return ToolResult(
                content=_cap(f"chart render failed (exit {rc}):\n{result.content}"),
                is_error=True,
                metadata={"root_cause": "chart-render-error"},
            )
        out_path = ctx.working_dir / args.output
        if not out_path.is_file():
            return ToolResult(content=f"chart script ran but {args.output} was not created:\n{result.content}", is_error=True)
        return ToolResult(content=f"chart written to {args.output}", metadata={"output": args.output})


def _chart_script(*, data: str, kind: str, x: str, ys: list[str], title: str, output: str) -> str:
    return (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "import pandas as pd\n"
        f"df = pd.read_csv({data!r})\n"
        "fig, ax = plt.subplots(figsize=(8, 5))\n"
        f"kind, x, ys = {kind!r}, {x!r}, {ys!r}\n"
        "if kind == 'hist':\n"
        "    cols = ys or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]\n"
        "    df[cols].plot(kind='hist', ax=ax, alpha=0.7)\n"
        "elif kind == 'scatter':\n"
        "    ax.scatter(df[x], df[ys[0]])\n"
        "    ax.set_xlabel(x); ax.set_ylabel(ys[0])\n"
        "else:\n"
        "    for col in ys:\n"
        "        if kind == 'bar':\n"
        "            ax.bar(df[x].astype(str), df[col], label=col)\n"
        "        else:\n"
        "            ax.plot(df[x], df[col], marker='o', label=col)\n"
        "    ax.set_xlabel(x)\n"
        "    if len(ys) > 1: ax.legend()\n"
        f"ax.set_title({title!r})\n"
        "fig.tight_layout()\n"
        f"fig.savefig({output!r}, dpi=120)\n"
        f"print('saved', {output!r})\n"
    )


# --------------------------------------------------------------------------- registry helper


def analysis_tool(name: str) -> BaseTool | None:
    """Build the analysis tool for ``name`` (worktree-scoped, ledger-free), or ``None`` if unknown."""
    if name == "warehouse_query":
        return WarehouseQueryTool()
    if name == "repo_search":
        return RepoSearchTool()
    if name == "notebook_run":
        return NotebookRunTool()
    if name == "chart_render":
        return ChartRenderTool()
    return None
