"""The Reviewer's standing routines (spec 13 §5).

The Reviewer declares no recurring work of its own — it is woken to judge work, not to schedule it.
This module is the seam: add a :class:`~chorus.roles.RoutineDeclaration` here and it provisions on
hire, with no kernel change. ``REVIEWER_ROUTINES`` is what
:func:`chorus_employee.reviewer.reviewer_plugin` hands to ``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

REVIEWER_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["REVIEWER_ROUTINES"]
