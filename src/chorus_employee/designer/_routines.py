"""The Designer's standing routines (designer §14).

A role can carry recurring work; hiring a Designer provisions these automatically (hire-time reconcile) —
no operator ``add_routine`` needed. ``DESIGNER_ROUTINES`` is what
:func:`chorus_employee.designer.designer_plugin` hands to ``RolePlugin.declared_routines``.

The routines (system-drift scan + accessibility audit) are added in the routines slice; until then the
Designer runs purely on assigned surfaces (the IC default path, designer §04).
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

DESIGNER_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["DESIGNER_ROUTINES"]
