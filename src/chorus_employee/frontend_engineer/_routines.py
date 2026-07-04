"""The Frontend Engineer's standing routines.

Like the Engineer, the Frontend Engineer declares no recurring work of its own — it acts on tasks
assigned to it. This module is the seam: add a :class:`~chorus.roles.RoutineDeclaration` here and it
provisions on hire, with no kernel change. ``FRONTEND_ENGINEER_ROUTINES`` is what
:func:`chorus_employee.frontend_engineer.frontend_engineer_plugin` hands to
``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

FRONTEND_ENGINEER_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["FRONTEND_ENGINEER_ROUTINES"]
