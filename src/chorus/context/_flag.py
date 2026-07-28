"""The rollout flag for pushed task context.

``CHORUS_TCP=1`` selects the packet path. Off by default, so a company on this build behaves exactly
as it did before: the existing prompt concatenations still run and the user message still carries its
ancestor chain.

The flag exists because PR 3 is the only step in this change that touches a live beat. Everything
before it is pure and unwired; this is where the prompt an employee actually reads changes shape, and
a per-run switch makes that reversible without a revert.

It is deliberately **short-lived**. Two paths that both build a beat's context is the duplication the
packet exists to end, so the flag should survive one live run and then be deleted along with the
branch it guards — not settle in as configuration.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

TCP_ENV_VAR = "CHORUS_TCP"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def tcp_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Whether this process should build beat context from the packet.

    ``env`` is injectable so the decision is testable without mutating the process environment —
    which would otherwise leak between tests running in the same session.
    """
    raw = (env if env is not None else os.environ).get(TCP_ENV_VAR, "")
    return raw.strip().lower() in _TRUTHY


__all__ = ["TCP_ENV_VAR", "tcp_enabled"]
