"""Overlay manifest resolution (spec 06 §2) — narrower-wins, capability is monotone.

Resolution layers ``base → overlay → overlay …`` left-to-right. Every layer may only
*narrow* capability (drop a tool, tighten the permission mode, restrict the memory scope,
escalate isolation); an overlay that tries to *widen* — add a tool, loosen a mode — is a
no-op. ``disallowed_tools`` always wins over the allow-list. The result can never carry a
capability the base lacked, in any layer order.
"""

from __future__ import annotations

import pytest

from chorus.roles import (
    Isolation,
    ManifestOverlay,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    resolve_manifest,
)

pytestmark = pytest.mark.unit


def _base() -> RoleManifest:
    return RoleManifest(
        system_prompt="engineer",
        tools=("read_file", "write_file", "run_command", "git"),
        disallowed_tools=("rm",),
        skills=("python", "review"),
        permission_mode=PermissionMode.ACCEPT_EDITS,
        memory_scope=MemoryScope.COMPANY,
        isolation=Isolation.WORKTREE,
    )


def test_no_overlays_returns_the_base_unchanged() -> None:
    base = _base()
    assert resolve_manifest(base) == base


def test_empty_overlay_is_identity() -> None:
    base = _base()
    assert resolve_manifest(base, ManifestOverlay()) == base


def test_overlay_drops_a_tool() -> None:
    resolved = resolve_manifest(_base(), ManifestOverlay(tools=("read_file", "write_file", "git")))
    assert resolved.tools == ("read_file", "write_file", "git")  # run_command narrowed out


def test_overlay_cannot_add_a_tool() -> None:
    # "curl" is not in the base allow-list; intersection drops it — no widening.
    resolved = resolve_manifest(
        _base(), ManifestOverlay(tools=("read_file", "write_file", "run_command", "git", "curl"))
    )
    assert "curl" not in resolved.tools
    assert resolved.tools == _base().tools


def test_disallow_wins_over_allow() -> None:
    # the overlay re-lists write_file in its allow set but also disallows it — deny wins.
    resolved = resolve_manifest(
        _base(),
        ManifestOverlay(tools=("read_file", "write_file"), disallowed_tools=("write_file",)),
    )
    assert resolved.tools == ("read_file",)
    assert "write_file" in resolved.disallowed_tools
    assert "rm" in resolved.disallowed_tools  # base deny preserved


def test_permission_mode_only_tightens() -> None:
    # PLAN is stricter than ACCEPT_EDITS -> applies.
    assert (
        resolve_manifest(_base(), ManifestOverlay(permission_mode=PermissionMode.PLAN)).permission_mode
        is PermissionMode.PLAN
    )


def test_permission_mode_cannot_loosen() -> None:
    # DONT_ASK is more permissive than the base ACCEPT_EDITS -> ignored.
    assert (
        resolve_manifest(
            _base(), ManifestOverlay(permission_mode=PermissionMode.DONT_ASK)
        ).permission_mode
        is PermissionMode.ACCEPT_EDITS
    )


def test_memory_scope_only_narrows() -> None:
    assert (
        resolve_manifest(_base(), ManifestOverlay(memory_scope=MemoryScope.PRIVATE)).memory_scope
        is MemoryScope.PRIVATE
    )


def test_memory_scope_cannot_widen() -> None:
    narrow = RoleManifest(system_prompt="x", memory_scope=MemoryScope.PROJECT)
    assert (
        resolve_manifest(narrow, ManifestOverlay(memory_scope=MemoryScope.COMPANY)).memory_scope
        is MemoryScope.PROJECT
    )


def test_isolation_escalates_to_remote() -> None:
    assert (
        resolve_manifest(_base(), ManifestOverlay(isolation=Isolation.REMOTE)).isolation
        is Isolation.REMOTE
    )


def test_isolation_cannot_de_escalate() -> None:
    remote = RoleManifest(system_prompt="x", isolation=Isolation.REMOTE)
    assert (
        resolve_manifest(remote, ManifestOverlay(isolation=Isolation.WORKTREE)).isolation
        is Isolation.REMOTE
    )


def test_skills_intersect() -> None:
    resolved = resolve_manifest(_base(), ManifestOverlay(skills=("python", "ml")))
    assert resolved.skills == ("python",)  # review dropped, ml never added


def test_system_prompt_last_non_none_wins() -> None:
    resolved = resolve_manifest(
        _base(),
        ManifestOverlay(system_prompt="stricter engineer"),
        ManifestOverlay(),  # None -> does not clobber the prior override
    )
    assert resolved.system_prompt == "stricter engineer"


def test_multiple_overlays_compose_narrowing() -> None:
    resolved = resolve_manifest(
        _base(),
        ManifestOverlay(tools=("read_file", "write_file", "run_command")),  # drop git
        ManifestOverlay(tools=("read_file", "write_file")),  # drop run_command
        ManifestOverlay(permission_mode=PermissionMode.PLAN, memory_scope=MemoryScope.PROJECT),
    )
    assert resolved.tools == ("read_file", "write_file")
    assert resolved.permission_mode is PermissionMode.PLAN
    assert resolved.memory_scope is MemoryScope.PROJECT


def test_capability_is_order_independent() -> None:
    a = ManifestOverlay(
        tools=("read_file", "write_file"),
        permission_mode=PermissionMode.PLAN,
        memory_scope=MemoryScope.TEAM,
        isolation=Isolation.REMOTE,
    )
    b = ManifestOverlay(
        tools=("read_file", "run_command"),
        permission_mode=PermissionMode.DEFAULT,
        memory_scope=MemoryScope.PRIVATE,
    )
    forward = resolve_manifest(_base(), a, b)
    backward = resolve_manifest(_base(), b, a)
    # capability fields are commutative (intersection / union / min / max)
    assert forward.tools == backward.tools == ("read_file",)
    assert forward.permission_mode is backward.permission_mode is PermissionMode.PLAN
    assert forward.memory_scope is backward.memory_scope is MemoryScope.PRIVATE
    assert forward.isolation is backward.isolation is Isolation.REMOTE
    assert set(forward.disallowed_tools) == set(backward.disallowed_tools)


def test_resolved_capability_never_exceeds_base() -> None:
    base = _base()
    resolved = resolve_manifest(
        base,
        ManifestOverlay(
            tools=("read_file", "write_file", "curl"),  # curl is a widen attempt
            permission_mode=PermissionMode.DONT_ASK,  # loosen attempt
            memory_scope=MemoryScope.COMPANY,  # widen attempt
            isolation=Isolation.WORKTREE,  # de-escalate attempt
        ),
    )
    assert set(resolved.tools) <= set(base.tools)
    assert set(resolved.disallowed_tools) >= set(base.disallowed_tools)
    assert resolved.permission_mode is PermissionMode.ACCEPT_EDITS  # unchanged, not loosened
    assert resolved.memory_scope is MemoryScope.COMPANY  # base already widest; stays
    assert resolved.isolation is Isolation.WORKTREE
