"""Analyst mid-beat specialists — lean cut.

Craft personas (data / modeling / narrative / scout) moved to skills on the main
employee. Isolation earners use Dream builtins (``explore`` / ``verify``) or
shared ``web_research`` via :func:`with_web_research`.
"""

from __future__ import annotations

from chorus.roles._subagent import SubagentSpec

ANALYST_SUBAGENTS: tuple[SubagentSpec, ...] = ()

__all__ = ["ANALYST_SUBAGENTS"]
