"""cms_draft wiring — backend selection by env + tool-name mapping (design doc: wiring)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus_tools.cms._config import cms_backend_from_env
from chorus_tools.cms._markdown import MarkdownCmsBackend
from chorus_tools.cms._strapi import StrapiCmsBackend

pytestmark = pytest.mark.unit


class TestBackendFromEnv:
    def test_markdown_when_strapi_env_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("STRAPI_URL", raising=False)
        monkeypatch.delenv("STRAPI_TOKEN", raising=False)
        assert isinstance(cms_backend_from_env(tmp_path), MarkdownCmsBackend)

    def test_strapi_when_env_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRAPI_URL", "http://localhost:1337")
        monkeypatch.setenv("STRAPI_TOKEN", "tok")
        assert isinstance(cms_backend_from_env(tmp_path), StrapiCmsBackend)

    def test_markdown_when_only_url_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Partial config must not half-wire a hosted backend.
        monkeypatch.setenv("STRAPI_URL", "http://localhost:1337")
        monkeypatch.delenv("STRAPI_TOKEN", raising=False)
        assert isinstance(cms_backend_from_env(tmp_path), MarkdownCmsBackend)


class TestToolNameMapping:
    def test_cms_draft_survives_dream_tool_names(self) -> None:
        from chorus_harness._factory import dream_tool_names

        assert dream_tool_names(("cms_draft",)) == ("cms_draft",)


class TestManifest:
    def test_marketer_holds_cms_draft(self) -> None:
        from chorus_employee.marketer import marketer_plugin

        assert "cms_draft" in marketer_plugin().manifest.tools
