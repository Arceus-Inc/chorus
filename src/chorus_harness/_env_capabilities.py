"""Env-capability degradation: a dead tool is dropped and disclosed, never dispatched (H2).

A tool whose backing service has no key in this environment can only burn calls — the live failure
was a marketer beat spending 6 ``web_search`` calls (all errored, no Tavily key on the server) and
then failing its DoD for lack of citations. The beat itself was fine; the tool was dead. So the
factory degrades rather than blocks: at materialize, :func:`degrade_for_env` drops the unbackable
tools from the role's config and appends one brief line disclosing the gap, so the model grounds
its work in what is actually possible and the evaluator judges the same. Checks are structural
(config tools + ``os.environ``, no role names); each returns the ``(tools_to_drop, brief_note)``
pair for one capability family, and new families (CMS backend, model key) append to ``_CHECKS``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace

from chorus.roles import RoleBeatConfig

_WEB_TOOLS = frozenset({"web_search", "web_extract"})
_TAVILY_ENV_KEYS = ("DREAM_TAVILY_API_KEY", "TAVILY_API_KEY")
_WEB_NOTE = (
    "Note: web research is unavailable in this environment (no search key); ground claims in "
    "repo artifacts and say so rather than inventing citations."
)


def _web_research(config: RoleBeatConfig) -> tuple[frozenset[str], str] | None:
    if _WEB_TOOLS & set(config.tools) and not any(k in os.environ for k in _TAVILY_ENV_KEYS):
        return _WEB_TOOLS, _WEB_NOTE
    return None


_CHECKS: tuple[Callable[[RoleBeatConfig], tuple[frozenset[str], str] | None], ...] = (
    _web_research,
)


def degrade_for_env(config: RoleBeatConfig) -> RoleBeatConfig:
    """Drop the tools this environment cannot back and disclose each gap in the brief."""
    for check in _CHECKS:
        degradation = check(config)
        if degradation is None:
            continue
        drop, note = degradation
        config = replace(
            config,
            tools=tuple(t for t in config.tools if t not in drop),
            system_prompt=config.system_prompt + "\n\n" + note,
        )
    return config


__all__ = ["degrade_for_env"]
