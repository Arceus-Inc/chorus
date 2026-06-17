"""Slug identity — the portable employee id derived from a name (spec 06 §3, spec 09 §3).

The slug *is* the employee id, so an org survives export → re-import into a fresh workforce
(new uuids elsewhere, same structure). Shared by every :class:`~chorus.workforce.Workforce`
backend so all of them mint identical ids for the same name.
"""

from __future__ import annotations

import re


def slugify(name: str) -> str:
    """Lowercase, collapse non-alphanumeric runs to a single hyphen, strip edges."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


__all__ = ["slugify"]
