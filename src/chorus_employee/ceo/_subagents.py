"""CEO mid-beat specialists — lean cut.

``advisor`` / ``researcher`` collapsed: use Dream ``explore``/``verify`` builtins
or shared ``web_research``. No duplicate persona roster.
"""

from __future__ import annotations

from chorus.roles._subagent import SubagentSpec

CEO_SUBAGENTS: tuple[SubagentSpec, ...] = ()

__all__ = ["CEO_SUBAGENTS"]
