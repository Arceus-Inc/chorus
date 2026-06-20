"""insights — a single observability platform over one experiment run's durable spines.

Point it at a finished (or in-flight) run's ``ledger.db`` and it reads the three traces a run leaves
behind — the **ledger** (tasks/runs/cost), the **event log** (witnessed tool calls), and the **memory
store** — and renders them as composable views:

    python -m experiments.insights path/to/ledger.db            # the headline snapshot
    python -m experiments.insights path/to/ledger.db all        # every section
    python -m experiments.insights path/to/ledger.db tree       # just the decomposition tree

Each view is a pure ``render(ExperimentSources) -> str``; :data:`VIEWS` is the name→view registry the
CLI and any notebook can drive.
"""

from __future__ import annotations

from collections.abc import Callable

from experiments.insights._decomposition import render as render_tree
from experiments.insights._ledger import render as render_ledger
from experiments.insights._memory import render as render_memory
from experiments.insights._overview import render as render_overview
from experiments.insights._sources import ExperimentSources
from experiments.insights._tools import render as render_tools

View = Callable[[ExperimentSources], str]

# The named views, in the order ``all`` prints them. ``overview`` leads; the rest drill in.
VIEWS: dict[str, View] = {
    "overview": render_overview,
    "ledger": render_ledger,
    "tree": render_tree,
    "memory": render_memory,
    "tools": render_tools,
}

__all__ = [
    "VIEWS",
    "ExperimentSources",
    "View",
    "render_ledger",
    "render_memory",
    "render_overview",
    "render_tools",
    "render_tree",
]
