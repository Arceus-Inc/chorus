"""GitWorkforce — org as data over an ``employees/<slug>/role.md`` tree (spec 06 §3, spec 09 §3).

Structural invariants only (role-registry validation is the facade's job, Slice C):
no ``reports_to`` cycle / self-edge, no duplicate slug, ``terminate`` is irreversible, the org
root (``reports_to is None``) cannot be terminated, and ``list`` excludes terminated employees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.errors import OrgInvariantViolation, UnknownEmployee
from chorus.workforce import EmployeeStatus, GitWorkforce

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path) -> str:
    return str(tmp_path / "org")


def test_hire_then_get_roundtrips(repo: str) -> None:
    wf = GitWorkforce(repo)
    hired = wf.hire(name="Alice", role="engineer")
    assert hired.id == "alice"
    assert hired.name == "Alice"
    assert hired.role == "engineer"
    assert hired.reports_to is None
    assert hired.status is EmployeeStatus.IDLE
    assert wf.get("alice") == hired


def test_hire_writes_role_md_with_frontmatter(repo: str) -> None:
    GitWorkforce(repo).hire(name="Alice", role="engineer")
    text = (Path(repo) / "employees" / "alice" / "role.md").read_text(encoding="utf-8")
    assert "role: engineer" in text
    assert "memory_scope: project" in text


def test_hire_with_reports_to_records_the_edge(repo: str) -> None:
    wf = GitWorkforce(repo)
    wf.hire(name="Boss", role="engineer")
    report = wf.hire(name="Alice", role="engineer", reports_to="boss")
    assert report.reports_to == "boss"


def test_memory_scope_defaults_to_project(repo: str) -> None:
    assert GitWorkforce(repo).hire(name="Alice", role="engineer").memory_scope == "project"


def test_get_unknown_raises(repo: str) -> None:
    with pytest.raises(UnknownEmployee):
        GitWorkforce(repo).get("nobody")


def test_hire_unknown_reports_to_raises(repo: str) -> None:
    with pytest.raises(UnknownEmployee):
        GitWorkforce(repo).hire(name="Alice", role="engineer", reports_to="ghost")


def test_hire_self_edge_is_rejected(repo: str) -> None:
    # "Boss" slugs to "boss"; reporting to its own slug is a self-cycle.
    with pytest.raises(OrgInvariantViolation):
        GitWorkforce(repo).hire(name="Boss", role="engineer", reports_to="boss")


def test_hire_duplicate_slug_is_rejected(repo: str) -> None:
    wf = GitWorkforce(repo)
    wf.hire(name="Alice", role="engineer")
    with pytest.raises(OrgInvariantViolation):
        wf.hire(name="alice", role="reviewer")


def test_list_excludes_terminated(repo: str) -> None:
    wf = GitWorkforce(repo)
    wf.hire(name="Boss", role="engineer")
    wf.hire(name="Alice", role="engineer", reports_to="boss")
    wf.terminate("alice")
    assert {e.id for e in wf.list()} == {"boss"}


def test_terminate_marks_terminated_irreversibly(repo: str) -> None:
    wf = GitWorkforce(repo)
    wf.hire(name="Boss", role="engineer")
    wf.hire(name="Alice", role="engineer", reports_to="boss")
    wf.terminate("alice")
    assert wf.get("alice").status is EmployeeStatus.TERMINATED


def test_terminate_is_idempotent(repo: str) -> None:
    wf = GitWorkforce(repo)
    wf.hire(name="Boss", role="engineer")
    wf.hire(name="Alice", role="engineer", reports_to="boss")
    wf.terminate("alice")
    wf.terminate("alice")  # no raise — irreversible, not an error to repeat
    assert wf.get("alice").status is EmployeeStatus.TERMINATED


def test_terminate_root_is_rejected(repo: str) -> None:
    wf = GitWorkforce(repo)
    wf.hire(name="Boss", role="engineer")  # reports_to is None -> the org root
    with pytest.raises(OrgInvariantViolation):
        wf.terminate("boss")


def test_terminate_unknown_raises(repo: str) -> None:
    with pytest.raises(UnknownEmployee):
        GitWorkforce(repo).terminate("nobody")


@pytest.mark.integration
def test_org_persists_across_instances(repo: str) -> None:
    GitWorkforce(repo).hire(name="Boss", role="engineer")
    GitWorkforce(repo).hire(name="Alice", role="engineer", reports_to="boss")
    fresh = GitWorkforce(repo)
    assert fresh.get("alice").reports_to == "boss"
    assert {e.id for e in fresh.list()} == {"boss", "alice"}
