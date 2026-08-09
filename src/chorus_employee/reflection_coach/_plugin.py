"""Pure Reflection Coach role assembly, safe for the default role catalog."""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.reflection_coach._dod import reflection_coach_dod
from chorus_employee.reflection_coach._harness import reflection_coach_manifest
from chorus_employee.reflection_coach._routines import REFLECTION_COACH_ROUTINES


def reflection_coach_plugin() -> RolePlugin:
    """The dedicated, isolated role boundary for managed reflection work."""
    return RolePlugin(
        name="reflection_coach",
        manifest=reflection_coach_manifest(),
        dod_generator=reflection_coach_dod,
        outcome_kind="reflection_proposal",
        declared_routines=REFLECTION_COACH_ROUTINES,
    )


__all__ = ["reflection_coach_plugin"]
