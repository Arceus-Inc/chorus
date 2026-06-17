"""The Engineer — the first employee to own a dedicated package (spec 06 §2, spec 11 M1).

One employee = one configured dream harness. This package gathers *everything* that makes an
Engineer that harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt).
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the Definition of Done (intent → typed :class:`~chorus.outcomes.Verifier`).

:func:`engineer_plugin` assembles them into the registrable
:class:`~chorus.roles.RolePlugin` triple. This is the **single source** of the Engineer:
``chorus.roles.default_roles`` imports it from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.engineer._dod import engineer_dod
from chorus_employee.engineer._harness import engineer_manifest


def engineer_plugin() -> RolePlugin:
    """The registrable Engineer role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="engineer",
        manifest=engineer_manifest(),
        dod_generator=engineer_dod,
        outcome_kind="pr",
    )


__all__ = ["engineer_plugin"]
