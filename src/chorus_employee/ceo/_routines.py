"""The CEO's standing routines (spec 13 §5).

The CEO declares no recurring work of its own yet — it acts on the governance and decision beats handed
to it. This module is the seam: add a :class:`~chorus.roles.RoutineDeclaration` here (e.g. a weekly
governance review) and it provisions on hire, with no kernel change. ``CEO_ROUTINES`` is what
:func:`chorus_employee.ceo.ceo_plugin` hands to ``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

CEO_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["CEO_ROUTINES"]
