"""Workspace containment — branch-isolated git worktrees for employees (spec 04 §4).

A :class:`CompanyWorkspace` gives every employee of a company its own git worktree (on a
``chorus/{employee}`` branch) under a shared company root, so their edits never collide; the work
merges back to the company ``main`` later. Dream-free: pure git side-effects the composition root
wires into the harness ``working_dir``.
"""

from __future__ import annotations

from chorus.workspace._worktree import (
    CompanyWorkspace,
    MergeResult,
    WorkspaceError,
    WorktreeWorkspace,
)

__all__ = ["CompanyWorkspace", "MergeResult", "WorkspaceError", "WorktreeWorkspace"]
