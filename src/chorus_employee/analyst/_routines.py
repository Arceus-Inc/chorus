"""The Analyst's standing routines (spec 13 §5).

The Analyst declares no recurring work of its own yet — it researches the questions handed to it.
This module is the seam: add a :class:`~chorus.roles.RoutineDeclaration` here (e.g. a weekly findings
digest) and it provisions on hire, with no kernel change. ``ANALYST_ROUTINES`` is what
:func:`chorus_employee.analyst.analyst_plugin` hands to ``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

ANALYST_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["ANALYST_ROUTINES"]
