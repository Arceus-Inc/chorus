"""Env-capability degradation (H2): a dead tool is dropped and disclosed, never dispatched.

Live failure: a marketer beat burned 6 ``web_search`` calls (all errored) because no Tavily key was
in the server env — the tool was dead before dispatch. At materialize the factory now drops tools
this environment cannot back and appends one brief line disclosing the gap, so the beat still runs
and the model grounds its claims in what is actually possible. Stub-harness pattern from
``tests/harness/test_recall_wiring.py``: dream's ``build_harness`` is monkeypatched so the captured
registry and the written role overlays are inspected without a provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration

_NOTE = (
    "Note: web research is unavailable in this environment (no search key); ground claims in "
    "repo artifacts and say so rather than inventing citations."
)
_WEB_TOOLS = {"web_search", "web_extract"}


def _factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, dict[str, Any]]:
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
    )
    return factory, captured


def _no_tavily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DREAM_TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def _generator_overlay(mat: Any) -> str:
    return (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text(encoding="utf-8")


def test_web_role_without_search_key_drops_the_tools_and_discloses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_tavily(monkeypatch)
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id=uid("mel"), name="Mel", role="marketer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert not names & _WEB_TOOLS  # the dead tools are gone from the effective toolset
    assert _NOTE in _generator_overlay(mat)  # and the brief says so


def test_web_role_with_search_key_keeps_the_tools_and_says_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id=uid("mel"), name="Mel", role="marketer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert _WEB_TOOLS <= names
    assert _NOTE not in _generator_overlay(mat)


def test_non_web_role_is_untouched_either_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_tavily(monkeypatch)
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id=uid("bex"), name="Bex", role="backend_engineer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert not names & _WEB_TOOLS  # never had them
    assert _NOTE not in _generator_overlay(mat)
