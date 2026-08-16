"""Roles & the workforce role layer (spec 06).

A role is the unit of heterogeneity — a ``(RoleManifest, DoDGenerator,
OutcomeKind)`` triple, packaged as a registrable :class:`RolePlugin`. The org
scales in *roles*, not kernel edits (spec 09 §1).
"""

from __future__ import annotations

from chorus.roles._beat_config import RoleBeatConfig, role_beat_config
from chorus.roles._defaults import default_roles
from chorus.roles._manifest import (
    DEFAULT_BEAT_TIMEOUT_S,
    DREAM_DEFAULT_MAX_SPRINTS,
    Isolation,
    McpServerSpec,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus.roles._overlay import ManifestOverlay, resolve_manifest
from chorus.roles._plugin import DoDGenerator, Role, RolePlugin
from chorus.roles._registry import RoleRegistry
from chorus.roles._routine_declaration import RoutineDeclaration
from chorus.roles._subagent import IsolationMode, SubagentSpec
from chorus.roles._surfaces import RoleSurfaceOverride, apply_role_surface_overrides

__all__ = [
    "DEFAULT_BEAT_TIMEOUT_S",
    "DREAM_DEFAULT_MAX_SPRINTS",
    "DoDGenerator",
    "Isolation",
    "IsolationMode",
    "ManifestOverlay",
    "McpServerSpec",
    "MemoryScope",
    "PermissionMode",
    "Role",
    "RoleBeatConfig",
    "RoleManifest",
    "RolePlugin",
    "RoleRegistry",
    "RoleSurfaceOverride",
    "RoutineDeclaration",
    "SandboxTier",
    "SubagentSpec",
    "apply_role_surface_overrides",
    "default_roles",
    "resolve_manifest",
    "role_beat_config",
]
