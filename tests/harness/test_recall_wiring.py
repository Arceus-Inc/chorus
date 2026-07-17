"""``recall`` wiring — the factory registers it and every worker role is materialized with it.

Mirrors ``tests/harness/test_factory.py``'s stub-harness pattern: dream's harness build is stubbed so
the role → tool-registry translation is tested without a provider. ``recall`` is rolled out to every
worker role (analyst, backend_engineer, designer, frontend_engineer, marketer, pm).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from chorus.ledger import Ledger
from chorus.memory import EpisodicStore, SprintDelta
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration


def _factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
        ledger=ledger,
    )
    return factory, captured


_RECALL_ROLES = (
    "analyst",
    "backend_engineer",
    "designer",
    "frontend_engineer",
    "marketer",
    "pm",
)


@pytest.mark.parametrize("role", _RECALL_ROLES)
def test_worker_role_materializes_with_recall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, role: str, ledger: Ledger
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path, ledger)
    factory.materialize(Employee(id=uid("emp"), name="Emp", role=role))
    names = {t.name for t in captured["registry"].list_tools()}
    assert {"recall", "get_run"}.issubset(names)


def test_recall_rides_the_company_ledger_not_a_local_db_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    """Episodic capture lives in the shared Postgres schema — materialize must not mint db files."""
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    assert not (tmp_path / "acme" / "memory" / "episodic.db").exists()
    EpisodicStore(ledger).count()  # the store opens on the same schema the factory wired


def _tools_line(overlay_toml: str) -> str:
    return next(line for line in overlay_toml.splitlines() if line.startswith("tools"))


def test_recall_is_admitted_to_the_read_only_evaluator_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # recall is safe/read-only (like memory_search), so the evaluator head — which keeps a narrowed
    # read-only toolset to verify with — must see it in its `tools = [...]` LIST, not just have the
    # word appear somewhere in the overlay's copied-in brief prose.
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    evaluator = (mat.working_dir / ".harness" / "roles" / "evaluator.toml").read_text(
        encoding="utf-8"
    )
    assert '"recall"' in _tools_line(evaluator)
    assert '"get_run"' in _tools_line(evaluator)


def test_materialize_does_not_inject_episodic_teaser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    """No prompt teaser / resume-nudge file — recall + TODO.md + skills carry orientation."""
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    store = EpisodicStore(ledger)
    ts = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    store.append(
        SprintDelta(
            run_id=uid("r_slug"),
            task_id=uid("t1"),
            employee_id="bex",
            scope="project",
            intent="add slugify to textutil",
            outcome="done",
            score=1.0,
            created_at=ts,
            recorded_at=ts,
        )
    )
    store.close()

    mat = factory.materialize(
        Employee(id="bex", name="Bex", role="backend_engineer"),
        task_id=uid("t2"),
    )
    teaser_path = mat.working_dir / ".harness" / "episodic-beat-start.json"
    assert not teaser_path.is_file()
    assert not (mat.working_dir / ".harness" / "episodic-resume-nudge.json").is_file()
    generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text(
        encoding="utf-8"
    )
    assert "Episodic orientation (auto)" not in generator
    assert "recall" in generator
    skills = mat.working_dir / ".harness" / "skills"
    assert (skills / "cross-beat-recall" / "SKILL.md").is_file()
    assert (skills / "cross-beat-resume" / "SKILL.md").is_file()


def test_backend_engineer_gets_todo_write_and_shared_cross_beat_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id=uid("eng"), name="Eng", role="backend_engineer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert {"recall", "get_run", "todo_write", "skill"}.issubset(names)
    skills = mat.working_dir / ".harness" / "skills"
    assert (skills / "cross-beat-recall" / "SKILL.md").is_file()
    assert (skills / "cross-beat-resume" / "SKILL.md").is_file()
