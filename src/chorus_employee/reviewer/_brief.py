"""The Reviewer's operating brief — the system prompt this employee runs under.

The Reviewer is the verifier for judgment-class work (B3.2): it renders an approve/block verdict on a
diff against the task's rubric. The composition root layers this onto each dream intra-task role as a
per-role overlay (see :func:`chorus_harness.write_role_overlays`).
"""

from __future__ import annotations

REVIEWER_BRIEF = "You render an approve/block verdict on a diff against the task's rubric."

__all__ = ["REVIEWER_BRIEF"]
