"""Public exception hierarchy (spec 10 §1).

Every error chorus itself raises is a :class:`ChorusError` subclass carrying a
stable string ``code`` consumers can branch on without parsing messages — the
same discipline as ``dream.errors.DreamError``.

``dream``-originated faults (``RunTaskError``, ``TaskCancelled``; spec 05) are
**not** re-wrapped — they surface as the dream types so the seam stays honest.
chorus only adds the org-level errors below.
"""

from __future__ import annotations


class ChorusError(Exception):
    """Root of everything chorus raises. Carries a stable ``code``."""

    code: str = "chorus.error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class InvalidIntake(ChorusError):
    """``submit()`` called with a bad intent, assignee, or DoD."""

    code = "chorus.invalid_intake"


class UnknownEmployee(ChorusError):
    """hire/assign referenced a missing employee."""

    code = "chorus.unknown_employee"


class OrgInvariantViolation(ChorusError):
    """An org-data edit broke an invariant.

    A ``reports_to`` cycle, a double assignee (employee XOR human), or an
    attempt to terminate the org root.
    """

    code = "chorus.org_invariant"


class RolePluginInvalid(ChorusError):
    """Role-plugin registration failed validation (spec 09 §1)."""

    code = "chorus.role_plugin_invalid"


class RolePluginConflict(ChorusError):
    """A slug was re-registered with a different definition without ``replace=True`` (spec 09 §1)."""

    code = "chorus.role_plugin_conflict"


class BudgetBlocked(ChorusError):
    """A submit/dispatch was refused by a hard-stop budget gate (spec 04 §3)."""

    code = "chorus.budget_blocked"


class PackageImportError(ChorusError):
    """A portable-package import failed a version gate or has unresolved refs (spec 09 §3)."""

    code = "chorus.package_import"


__all__ = [
    "BudgetBlocked",
    "ChorusError",
    "InvalidIntake",
    "OrgInvariantViolation",
    "PackageImportError",
    "RolePluginConflict",
    "RolePluginInvalid",
    "UnknownEmployee",
]
