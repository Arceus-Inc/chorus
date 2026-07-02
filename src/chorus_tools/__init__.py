"""Chorus capabilities exposed to the model as dream tools (Path A composition layer).

``chorus_tools`` is the seam where a chorus capability becomes **model-callable**: each tool here is a
dream ``BaseTool`` wrapping a dream-free chorus service. The dream import lives in this layer (like
``chorus_cli``) so core ``chorus`` stays dream-free. Build a role's registry with
:func:`chorus_tool_registry` and hand it to ``dream.build_harness(registry=…)``.
"""

from __future__ import annotations

from chorus_tools._analysis import (
    ChartRenderTool,
    NotebookRunTool,
    RepoSearchTool,
    WarehouseQueryTool,
    analysis_tool,
)
from chorus_tools._decompose import DecomposeInput, DecomposeTool
from chorus_tools._manager_actions import (
        AssignTaskInput,
        AssignTaskTool,
        SubmitTaskInput,
        SubmitTaskTool,
)
from chorus_tools._registry import chorus_tool_registry
from chorus_tools._submit_verdict import SubmitVerdictInput, SubmitVerdictTool

__all__ = [
        "AssignTaskInput",
        "AssignTaskTool",
        "ChartRenderTool",
        "DecomposeInput",
        "DecomposeTool",
        "NotebookRunTool",
        "RepoSearchTool",
        "SubmitTaskInput",
        "SubmitTaskTool",
        "SubmitVerdictInput",
        "SubmitVerdictTool",
        "WarehouseQueryTool",
        "analysis_tool",
        "chorus_tool_registry",
]
