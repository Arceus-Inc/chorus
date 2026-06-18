"""The Manager's operating brief — the system prompt this employee runs under.

A Manager orchestrates: it decomposes work into children, dispatches them, and integrates their
completed subtree (the non-blocking delegation model, B1.2/B1.3). The composition root layers this
onto each dream intra-task role as a per-role overlay (see :func:`chorus_harness.write_role_overlays`).
"""

from __future__ import annotations

MANAGER_BRIEF = "You decompose work, dispatch children, and integrate their completed subtree."

__all__ = ["MANAGER_BRIEF"]
