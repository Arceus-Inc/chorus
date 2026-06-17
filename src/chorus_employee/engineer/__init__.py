"""The Engineer — the first employee to own a dedicated package (spec 06 §2, spec 11 M1).

One employee = one configured dream harness. This package gathers *everything* that makes an
Engineer that harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt).
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the Definition of Done (intent → typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._lander`  — the outcome lander (a passed beat → a ``pr`` artifact).

:func:`engineer_plugin` assembles the role triple; :func:`engineer_lander` provides the matching
:class:`~chorus.outcomes.OutcomeLander`. This is the **single source** of the Engineer:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.engineer._dod import engineer_dod
from chorus_employee.engineer._harness import engineer_manifest
from chorus_employee.engineer._lander import EngineerLander, engineer_lander


def engineer_plugin() -> RolePlugin:
    """The registrable Engineer role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="engineer",
        manifest=engineer_manifest(),
        dod_generator=engineer_dod,
        outcome_kind="pr",
    )


__all__ = ["EngineerLander", "engineer_lander", "engineer_plugin"]
