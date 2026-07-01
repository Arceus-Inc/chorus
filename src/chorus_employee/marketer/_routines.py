"""The Marketer's standing routines (design doc §13).

The Marketer declares recurring work that makes her a standing growth loop (performance watch,
experiment readout, content refresh, brand-drift scan). These are a follow-up slice — Slice 0
ships the bare plugin with no routines so the lifecycle can be e2e-tested first.

``MARKETER_ROUTINES`` is what :func:`chorus_employee.marketer.marketer_plugin` hands to
``RolePlugin.declared_routines``.
"""

from __future__ import annotations

from chorus.roles._routine_declaration import RoutineDeclaration

MARKETER_ROUTINES: tuple[RoutineDeclaration, ...] = ()

__all__ = ["MARKETER_ROUTINES"]
