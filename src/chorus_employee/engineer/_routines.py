"""The Engineer's standing routines (spec 13 §5).

The Engineer declares no recurring work of its own — it acts on tasks assigned to it. This module is
the seam: add a :class:`~chorus.roles.RoutineDeclaration` here and it provisions on hire, with no
kernel change. ``ENGINEER_ROUTINES`` is what :func:`chorus_employee.engineer.engineer_plugin` hands to
``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

ENGINEER_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["ENGINEER_ROUTINES"]
