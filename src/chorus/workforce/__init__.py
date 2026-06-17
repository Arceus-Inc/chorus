"""The Workforce — org as data (spec 06 §3).

The org chart **is** the ``employee.reports_to`` adjacency list — there is no
``teams`` table; team structure is emergent. Hire/fire is a data edit, not a
process spawn. An :class:`Employee` has no continuous existence: each beat
*rehydrates* it from ``(employee row + role manifest + memory scope + ledger
history)``, runs one ``run_task``, and dissolves (B1.1). Continuity lives in the
ledger + memory git, never in a running thing.

This package is a facade (spec I6): the :class:`Employee` value object and its
:class:`EmployeeStatus` live in ``_models``, the swappable :class:`Workforce`
seam in ``_protocol``, the ledger-backed default :class:`LedgerWorkforce` (the
single live org store) in ``_ledger``, and the portable git-markdown
export/import form :class:`GitWorkforce` in ``_git``. Import the public names
from here, not the submodules.
"""

from __future__ import annotations

from chorus.workforce._git import GitWorkforce
from chorus.workforce._ledger import EmployeeStore, LedgerWorkforce
from chorus.workforce._models import Employee, EmployeeStatus
from chorus.workforce._package import copy_org
from chorus.workforce._protocol import Workforce

__all__ = [
    "Employee",
    "EmployeeStatus",
    "EmployeeStore",
    "GitWorkforce",
    "LedgerWorkforce",
    "Workforce",
    "copy_org",
]
