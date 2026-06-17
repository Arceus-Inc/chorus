"""CLI beat composition can opt Engineer into Dream surfaces."""

from __future__ import annotations

import pytest

from chorus_cli._beats import default_roles_from_env

pytestmark = pytest.mark.unit


def _engineer():
    return next(plugin for plugin in default_roles_from_env() if plugin.name == "engineer")


def test_empty_surfaces_env_keeps_engineer_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHORUS_ENGINEER_SURFACES", raising=False)
    engineer = _engineer()

    assert engineer.manifest.skills == ()
    assert engineer.manifest.mcp is False
    assert engineer.manifest.plugins is False


def test_surfaces_env_enables_requested_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHORUS_ENGINEER_SURFACES", " skills, mcp, plugins ")
    engineer = _engineer()

    assert engineer.manifest.skills == ("project",)
    assert "skill" in engineer.manifest.tools
    assert engineer.manifest.mcp is True
    assert engineer.manifest.plugins is True