"""The Manager's standing routines (spec 13 §5).

The Manager declares no recurring work of its own — it orchestrates the goals handed to it. This
module is the seam: add a :class:`~chorus.roles.RoutineDeclaration` here and it provisions on hire,
with no kernel change. ``MANAGER_ROUTINES`` is what :func:`chorus_employee.manager.manager_plugin`
hands to ``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

MANAGER_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["MANAGER_ROUTINES"]
