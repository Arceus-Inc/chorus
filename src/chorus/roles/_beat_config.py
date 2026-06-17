"""RoleBeatConfig — the dream-free, beat-ready projection of a role (spec 06 §2, spec 05).

A role's :class:`RoleManifest` is the full standing contract; a *beat* needs only a slice of it: the
system prompt, the tool allow-list, the permission posture, and the memory scope. :func:`role_beat_config`
projects the manifest into that slice as plain strings — no dream import — so any front end (the public
``Chorus`` API, the CLI ``chat``) can resolve an employee's role to a beat config agnostically. The
composition root turns this into a concrete dream harness (the chorus→dream tool-name mapping and the
``run_role`` call live there, at the seam). Tool names stay *chorus* names here.
"""

from __future__ import annotations

from dataclasses import dataclass

from chorus.roles._manifest import RoleManifest


@dataclass(frozen=True)
class RoleBeatConfig:
    """What a beat needs from a role, as plain (dream-compatible) values.

    ``permission_mode`` is already the dream-wire string (the chorus enum is a subset of dream's, by
    value); ``tools`` are chorus tool names — the seam maps them to dream's. Frozen so it is hashable
    and safe to share across async beats.
    """

    system_prompt: str
    tools: tuple[str, ...] = ()
    permission_mode: str = "default"
    memory_scope: str = "project"


def role_beat_config(manifest: RoleManifest) -> RoleBeatConfig:
    """Project a chorus :class:`RoleManifest` into the beat-ready :class:`RoleBeatConfig`."""
    return RoleBeatConfig(
        system_prompt=manifest.system_prompt,
        tools=manifest.tools,
        permission_mode=manifest.permission_mode.value,
        memory_scope=manifest.memory_scope.value,
    )


__all__ = ["RoleBeatConfig", "role_beat_config"]
