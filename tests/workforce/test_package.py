"""copy_org — the GitWorkforce ⇄ ledger codec (org as data, spec 09 §3).

The portable git-markdown tree is the *serialization* of the live ledger org, not a second store:
export copies the ledger workforce into the markdown tree, import re-materializes it into a (fresh)
ledger. Because every :class:`Workforce` keys employees by ``slugify(name)`` and carries
``reports_to`` as the parent's slug, the org structure round-trips — and ``copy_org`` writes managers
before reports so each ``reports_to`` edge resolves as it lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.errors import OrgInvariantViolation
from chorus.ledger import SqliteLedger
from chorus.workforce import Employee, GitWorkforce, LedgerWorkforce, copy_org

pytestmark = pytest.mark.integration


def _seed(wf: LedgerWorkforce) -> None:
    wf.hire(name="Boss", role="engineer")
    wf.hire(name="Alice", role="engineer", reports_to="boss")
    wf.hire(name="Bob", role="engineer", reports_to="boss")


def test_export_ledger_to_markdown_writes_the_tree(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(LedgerWorkforce(ledger.employees))
    copied = copy_org(LedgerWorkforce(ledger.employees), GitWorkforce(str(tmp_path / "org")))
    assert copied == 3
    assert (tmp_path / "org" / "employees" / "alice" / "role.md").exists()


def test_round_trip_ledger_to_markdown_to_fresh_ledger(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    _seed(LedgerWorkforce(ledger.employees))
    copy_org(LedgerWorkforce(ledger.employees), GitWorkforce(str(tmp_path / "org")))

    fresh = SqliteLedger.open(":memory:")
    try:
        copy_org(GitWorkforce(str(tmp_path / "org")), LedgerWorkforce(fresh.employees))
        wf = LedgerWorkforce(fresh.employees)
        assert {e.id for e in wf.list()} == {"boss", "alice", "bob"}
        assert wf.get("alice").reports_to == "boss"  # the org edge survived the round-trip
        assert fresh.employees.get("alice") is not None  # a real, assignable ledger row
    finally:
        fresh.close()


def test_copy_excludes_terminated(ledger: SqliteLedger, tmp_path: Path) -> None:
    source = LedgerWorkforce(ledger.employees)
    _seed(source)
    source.terminate("bob")
    copy_org(source, GitWorkforce(str(tmp_path / "org")))
    assert {e.id for e in GitWorkforce(str(tmp_path / "org")).list()} == {"boss", "alice"}


def test_copy_writes_parents_before_reports(ledger: SqliteLedger, tmp_path: Path) -> None:
    # A report listed before its manager must still land — the codec orders parents first, so the
    # reports_to edge resolves when the report is hired (otherwise hire raises UnknownEmployee).
    source = LedgerWorkforce(ledger.employees)
    source.hire(name="Boss", role="engineer")
    source.hire(name="Zara", role="engineer", reports_to="boss")  # "zara" sorts after "boss"
    copied = copy_org(source, GitWorkforce(str(tmp_path / "org")))
    assert copied == 2


def test_cycle_in_source_is_rejected(tmp_path: Path) -> None:
    a = Employee(id="a", name="A", role="engineer", reports_to="b")
    b = Employee(id="b", name="B", role="engineer", reports_to="a")
    with pytest.raises(OrgInvariantViolation):
        copy_org(_FakeSource([a, b]), GitWorkforce(str(tmp_path / "org")))


class _FakeSource:
    """A minimal :class:`Workforce` source that yields a fixed (here, cyclic) employee list."""

    def __init__(self, employees: list[Employee]) -> None:
        self._employees = employees

    def list(self) -> list[Employee]:
        return self._employees

    def get(
        self, employee_id: str
    ) -> Employee:  # pragma: no cover - unused by copy_org's source path
        raise KeyError(employee_id)

    def hire(
        self, *, name: str, role: str, reports_to: str | None = None
    ) -> Employee:  # pragma: no cover
        raise NotImplementedError

    def terminate(self, employee_id: str) -> None:  # pragma: no cover
        raise NotImplementedError
