"""Roles & the workforce role layer (spec 06).

A role is the unit of heterogeneity — a ``(RoleManifest, DoDGenerator,
OutcomeKind)`` triple, packaged as a registrable :class:`RolePlugin`. The org
scales in *roles*, not kernel edits (spec 09 §1).
"""

from __future__ import annotations

from chorus.roles._defaults import default_roles
from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode, RoleManifest
from chorus.roles._plugin import DoDGenerator, Role, RolePlugin

__all__ = [
    "DoDGenerator",
    "Isolation",
    "MemoryScope",
    "PermissionMode",
    "Role",
    "RoleManifest",
    "RolePlugin",
    "default_roles",
]
