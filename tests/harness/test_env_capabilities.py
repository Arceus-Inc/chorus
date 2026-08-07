"""Env-capability degradation (H2): a dead tool is dropped and disclosed, never dispatched.

Live failure pattern: a marketer beat burned web calls because the backing service was missing.
Web research is now ``browser_run`` against Chromium CDP. At materialize the factory drops
``browser_run`` when no CDP endpoint is configured and discloses the gap in the brief.
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
    "Note: browser research is unavailable in this environment (no Chromium CDP endpoint; "
    "set DREAM_CHROMIUM_CDP_URL). web_fetch still works for direct page reads; ground "
    "claims in repo artifacts or fetched pages and say so rather than inventing citations."
)
_WEB_TOOLS = {"browser_run", "web_search", "web_extract"}


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


def _no_cdp(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DREAM_CHROMIUM_CDP_URL",
        "DREAM_CHROMIUM_CDP_WS",
        "BU_CDP_URL",
        "BU_CDP_WS",
        "DREAM_TAVILY_API_KEY",
        "TAVILY_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def _generator_overlay(mat: Any) -> str:
    return (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text(encoding="utf-8")


def test_web_role_without_cdp_drops_the_tools_and_discloses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_cdp(monkeypatch)
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id=uid("mel"), name="Mel", role="marketer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert not names & _WEB_TOOLS
    # web_fetch needs only egress, so it is NOT degraded with the CDP-backed tools.
    assert "web_fetch" in names
    assert _NOTE in _generator_overlay(mat)


def test_web_role_with_cdp_keeps_browser_run_and_says_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_cdp(monkeypatch)
    monkeypatch.setenv("DREAM_CHROMIUM_CDP_URL", "http://127.0.0.1:9222")
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id=uid("mel"), name="Mel", role="marketer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert "browser_run" in names
    assert _NOTE not in _generator_overlay(mat)


def test_backend_engineer_without_cdp_drops_browser_run_and_discloses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_cdp(monkeypatch)
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id=uid("bex"), name="Bex", role="backend_engineer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert "browser_run" not in names
    assert _NOTE in _generator_overlay(mat)
