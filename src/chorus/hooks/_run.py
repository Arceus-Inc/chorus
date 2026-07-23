"""The hook runner — bounded, isolated, pulse-friendly."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chorus.ledger import Ledger

OrgHook = Callable[["Ledger"], int]

_logger = logging.getLogger(__name__)


def run_org_hooks(ledger: Ledger, hooks: tuple[OrgHook, ...]) -> int:
    """Run every hook against the ledger; return the total actions taken.

    A crashing hook is logged and skipped — reactions are best-effort helpers, and a bug in
    one must never take the heartbeat down with it.
    """
    fired = 0
    for hook in hooks:
        try:
            fired += hook(ledger)
        except Exception:
            _logger.exception("org hook %r failed; pulse continues", getattr(hook, "__name__", hook))
    return fired


__all__ = ["OrgHook", "run_org_hooks"]
