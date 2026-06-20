"""``org.workforce`` — org-as-data: role plugins + portable export/import (spec 14 §5.5, spec 09).

``register_role`` adds a role plugin (fail-closed + idempotent); ``export``/``import_`` serialize the
live ledger org to/from a portable git-markdown tree. Migrated from the flat verbs (spec 14
'migrate all'). ``import_`` has a trailing underscore — ``import`` is a Python keyword.
"""

from __future__ import annotations

from chorus.roles import RolePlugin, RoleRegistry
from chorus.workforce import GitWorkforce, Workforce, copy_org


class WorkforceFacade:
    """The ``org.workforce`` surface — register_role / export / import_."""

    def __init__(self, workforce: Workforce, roles: RoleRegistry) -> None:
        self._workforce = workforce
        self._roles = roles

    def register_role(self, plugin: RolePlugin, *, replace: bool = False) -> None:
        """Register a role plugin — fail-closed + idempotent (spec 09 §1)."""
        self._roles.register(plugin, replace=replace)

    def export(self, org_repo: str) -> int:
        """Serialize the live org to a portable git-markdown tree; return the count exported."""
        return copy_org(self._workforce, GitWorkforce(org_repo))

    def import_(self, org_repo: str) -> int:
        """Materialize a git-markdown org into the live ledger (managers first); return the count."""
        return copy_org(GitWorkforce(org_repo), self._workforce)


__all__ = ["WorkforceFacade"]
