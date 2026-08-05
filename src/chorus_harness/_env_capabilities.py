"""Env-capability degradation: a dead tool is dropped and disclosed, never dispatched (H2).

A tool whose backing service is missing in this environment can only burn calls. Previously
that was Tavily (``web_search`` / ``web_extract``). Web research is now ``browser_run`` against
a self-hosted Chromium CDP endpoint (``DREAM_CHROMIUM_CDP_URL`` / ``DREAM_CHROMIUM_CDP_WS``).
At materialize, :func:`degrade_for_env` drops ``browser_run`` when no CDP endpoint is
configured and appends one brief line disclosing the gap.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace

from chorus.roles import RoleBeatConfig

_WEB_TOOLS = frozenset({"browser_run", "web_search", "web_extract"})
_CDP_ENV_KEYS = ("DREAM_CHROMIUM_CDP_URL", "DREAM_CHROMIUM_CDP_WS", "BU_CDP_URL", "BU_CDP_WS")
_WEB_NOTE = (
    "Note: browser research is unavailable in this environment (no Chromium CDP endpoint; "
    "set DREAM_CHROMIUM_CDP_URL); ground claims in repo artifacts and say so rather than "
    "inventing citations."
)


def _web_research(config: RoleBeatConfig) -> tuple[frozenset[str], str] | None:
    if _WEB_TOOLS & set(config.tools) and not any(
        os.environ.get(k, "").strip() for k in _CDP_ENV_KEYS
    ):
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
