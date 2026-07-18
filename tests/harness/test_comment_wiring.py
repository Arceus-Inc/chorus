"""Comment wiring (OM-3) — every ledger-backed beat can coordinate, and its inbox is in the brief.

Mirrors the stub-harness pattern of ``test_recall_wiring.py``: dream's harness build is stubbed so
the role → tool-registry translation and the brief injection are tested without a provider. The
rollout is universal-by-ledger (the ``get_run`` precedent): comments are communication, not
authority — they run nothing — so every employee with a ledger gets the verbs.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from chorus.ledger import Message, Task
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration


def _factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Any = None
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    kwargs: dict[str, Any] = {}
    if ledger is not None:
        kwargs["ledger"] = ledger
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
        **kwargs,
    )
    return factory, captured


def test_ledger_backed_role_materializes_with_the_comment_verbs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id=uid("bex"), name="Bex", role="backend_engineer"))
        factory, captured = _factory(monkeypatch, tmp_path, ledger)
        factory.materialize(Employee(id=uid("bex"), name="Bex", role="backend_engineer"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert {"comment", "read_comments"}.issubset(names)
    finally:
        ledger.close()


def test_ledger_free_materialization_has_no_comment_verbs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id=uid("solo"), name="Solo", role="backend_engineer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert "comment" not in names


def test_unread_comments_are_injected_into_the_brief_and_consumed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The inbox IS the brief (paperclip: inbox = assigned tasks + comments). Injection marks
    the messages read so the next beat isn't re-nudged forever."""
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id="mia", name="Mia", role="manager"))
        ledger.employees.create(Employee(id="rex", name="Rex", role="backend_engineer"))
        task = ledger.tasks.submit(
            Task(id=str(uuid.uuid4()), intent="write the parser", assignee_employee_id="rex")
        )
        ledger.messages.send(
            Message(
                id=str(uuid.uuid4()),
                from_employee_id="mia",
                to_employee_id="rex",
                task_id=task.id,
                body="parser must handle CRLF line endings",
            )
        )
        factory, _ = _factory(monkeypatch, tmp_path, ledger)
        mat = factory.materialize(
            Employee(id="rex", name="Rex", role="backend_engineer"), task_id=task.id
        )
        generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text("utf-8")
        assert "parser must handle CRLF line endings" in generator
        assert "mia" in generator
        assert ledger.messages.inbox("rex") == []  # consumed — the thread stays in for_task
    finally:
        ledger.close()
