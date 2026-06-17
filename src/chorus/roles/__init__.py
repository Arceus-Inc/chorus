"""Roles & the workforce role layer (spec 06).

A role is the unit of heterogeneity — a ``(RoleManifest, DoDGenerator,
OutcomeKind)`` triple, packaged as a registrable :class:`RolePlugin`. The org
scales in *roles*, not kernel edits (spec 09 §1).
"""

from __future__ import annotations

from chorus.roles._beat_config import RoleBeatConfig, role_beat_config
from chorus.roles._defaults import default_roles
from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode, RoleManifest
from chorus.roles._overlay import ManifestOverlay, resolve_manifest
from chorus.roles._plugin import DoDGenerator, Role, RolePlugin
from chorus.roles._registry import RoleRegistry

__all__ = [
    "DoDGenerator",
    "Isolation",
    "ManifestOverlay",
    "MemoryScope",
    "PermissionMode",
    "Role",
    "RoleBeatConfig",
    "RoleManifest",
    "RolePlugin",
    "RoleRegistry",
    "default_roles",
    "resolve_manifest",
    "role_beat_config",
]
