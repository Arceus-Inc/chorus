"""Chorus capabilities exposed to the model as dream tools (Path A composition layer).

``chorus_tools`` is the seam where a chorus capability becomes **model-callable**: each tool here is a
dream ``BaseTool`` wrapping a dream-free chorus service. The dream import lives in this layer (like
``chorus_cli``) so core ``chorus`` stays dream-free. Build a role's registry with
:func:`chorus_tool_registry` and hand it to ``dream.build_harness(registry=…)``.
"""

from __future__ import annotations

from chorus_tools._brand_lint import BrandFinding, BrandLintInput, BrandLintTool
from chorus_tools._decompose import DecomposeInput, DecomposeTool
from chorus_tools._go_live import GoLiveAction, GoLiveInput, GoLiveTool
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
	"BrandFinding",
	"BrandLintInput",
	"BrandLintTool",
	"DecomposeInput",
	"DecomposeTool",
	"GoLiveAction",
	"GoLiveInput",
	"GoLiveTool",
	"SubmitTaskInput",
	"SubmitTaskTool",
	"SubmitVerdictInput",
	"SubmitVerdictTool",
	"chorus_tool_registry",
]
