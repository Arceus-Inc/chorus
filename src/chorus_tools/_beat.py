"""Best-effort read of the per-beat task identity from a worktree.

Both ``cms_draft`` (for its idempotency key) and ``execute_go_live`` (for the gate it may execute)
need the current task id, and both must degrade gracefully outside a real beat (a local run or a
unit test with no ``.harness/beat-context.json``). One helper instead of the guarded
``BeatContext.read`` block copied into each tool.
"""

from __future__ import annotations

from pathlib import Path


def task_id_or_none(working_dir: Path | None) -> str | None:
    """Return the beat's ``task_id``, or ``None`` when there is no beat context to read."""
    from chorus.heartbeat import BeatContext

    if working_dir is None:
        return None
    try:
        return BeatContext.read(working_dir).task_id
    except (FileNotFoundError, KeyError, ValueError):
        return None


__all__ = ["task_id_or_none"]
