"""Build the dream tool registry that makes chorus capabilities model-callable (Path A).

The session's model-facing toolset is the **registry contents** rendered to the provider's ``tools``
wire shape — *not* ``harness.register_tool`` (which never reaches the model), and *not* the manifest
allow-list (the default engine factory ignores it). So a role's effective toolset **is** the registry
it is built with. :func:`chorus_tool_registry` is therefore role-scoped: by default it contains only
the given chorus tools, so the model is offered exactly the role's capabilities. Pass the result to
``dream.build_harness(registry=…)``. Set ``include_builtins=True`` for a role that also needs the dream
file/shell/git tools (e.g. an engineer, or a manager that also reads files).
"""

from __future__ import annotations

from dream.tools._base import BaseTool
from dream.tools._registry import ToolRegistry, ToolSource
from dream.tools.builtin import default_registry


def chorus_tool_registry(*tools: BaseTool, include_builtins: bool = False) -> ToolRegistry:
    """A role-scoped dream registry of ``tools`` (plus the built-ins when ``include_builtins``).

    Tools are registered as ``ToolSource.DEFAULT`` — trusted at the active sandbox tier (a host /
    first-party capability), so they are offered to the model without a tool-tier override.
    """
    registry = default_registry() if include_builtins else ToolRegistry()
    for tool in tools:
        registry.register(tool, source=ToolSource.DEFAULT)
    return registry


__all__ = ["chorus_tool_registry"]
