"""The Analyst's Tier-1 subagents — bounded specialists it can dispatch mid-beat.

Each is a capability-minimized teammate the Analyst spawns with dream's ``spawn_subagent`` tool while
working a single beat. Every subagent's tools are a **subset** of the Analyst's own toolset (the
composition root intersects them at materialize), so a specialist can only ever narrow what the
Analyst can do, never widen it. They are ephemeral: they do focused work, return text, and dissolve —
no org hierarchy, no recursion (``spawn_subagent`` is disallowed to them).
"""

from __future__ import annotations

from chorus.roles._subagent import SubagentSpec

# Tier-1, role-owned. Tools are CHORUS names (mapped to dream + intersected with the Analyst's toolset).
# Descriptions are imperative: a spawned child's system prompt is generated from name + description, so
# telling it to USE its tools (read the files in its working directory, run a script) is what makes the
# specialist actually act rather than claim it cannot.
ANALYST_SUBAGENTS: tuple[SubagentSpec, ...] = (
    SubagentSpec(
        name="data",
        description=(
            "Load, clean, and shape the dataset. You work in the analyst's working directory where the "
            "source files live: use `repo_search`/`read_file` to find them, `warehouse_query` to pull "
            "from the SQL warehouse, and `notebook_run` (pandas) to produce the base tables — typed "
            "columns, derived rates, group-bys, joins. Return the computed numbers, not prose."
        ),
        tools=(
            "read_file",
            "repo_search",
            "warehouse_query",
            "notebook_run",
            "run_command",
            "read_offloaded",
        ),
    ),
    SubagentSpec(
        name="modeling",
        description=(
            "Compute statistics and fit simple models — correlations, regressions/trends, aggregates — "
            "and visualise them. You work in the analyst's working directory: read the data, compute "
            "with `notebook_run` (pandas/numpy), render a chart with `chart_render` if it helps, and "
            "report the exact numeric results."
        ),
        tools=(
            "read_file",
            "warehouse_query",
            "notebook_run",
            "chart_render",
            "run_command",
            "read_offloaded",
        ),
    ),
    SubagentSpec(
        name="critic",
        description=(
            "Independently red-team the analysis. You work in the same directory as the data and the "
            "analysis: read the source file(s) with `read_file`, then independently recompute the key "
            "numbers from scratch with `notebook_run` (or a `run_command` script). Report whether each "
            "figure matches, with exact recomputed values, and flag any discrepancy, arithmetic slip, "
            "or unsupported claim. Do not write the findings doc."
        ),
        tools=("read_file", "warehouse_query", "notebook_run", "run_command", "read_offloaded"),
    ),
    SubagentSpec(
        name="scout",
        description=(
            "Research the world. Use `browser_run` to open a real Chromium browser (search, navigate, "
            "read rendered pages), then return a concise, cited summary (claim + the URL it came from). "
            "Helpers are pre-imported: new_tab, page_info, js, wait_for_load. End scripts with "
            "print(json.dumps({...})). When a result says `Full output saved to: <file>`, read that "
            "full payload with `read_offloaded` (not `read_file`). Never invent a source or a URL."
        ),
        tools=("browser_run", "web_fetch", "read_file", "read_offloaded"),
    ),
    SubagentSpec(
        name="narrative",
        description=(
            "Draft a clear, reviewer-ready write-up of already-computed results: the answer, the "
            "evidence, and the implication, with the exact numbers given to you. Use read_file to read "
            "the computed outputs; never invent or recompute numbers."
        ),
        tools=("read_file", "write_file"),
    ),
)

__all__ = ["ANALYST_SUBAGENTS"]
