"""Typed deliverable kinds a role can land (spec 04 §2, spec 17).

``outcome_kind`` on a role plugin is stored as a string for registration; this enum is the
kernel/tool vocabulary so assignment and landing never traffic in untyped kind names.
"""

from __future__ import annotations

from enum import StrEnum


class OutcomeKind(StrEnum):
    """The deliverable a role lands — what ``done`` must mean for that craft."""

    PR = "pr"
    DOC = "doc"
    FINDING = "finding"
    SUBTREE = "subtree"
    VERDICT = "verdict"
    DESIGN = "design"
    CONTENT = "content"
    DIRECTIVE = "directive"


__all__ = ["OutcomeKind"]
