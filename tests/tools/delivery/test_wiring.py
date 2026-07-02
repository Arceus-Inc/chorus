"""execute_go_live wiring — name mapping, manifest, brief (design doc: wiring)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestToolNameMapping:
    def test_execute_go_live_survives_dream_tool_names(self) -> None:
        from chorus_harness._factory import dream_tool_names

        assert dream_tool_names(("execute_go_live",)) == ("execute_go_live",)


class TestManifest:
    def test_marketer_holds_execute_go_live(self) -> None:
        from chorus_employee.marketer import marketer_plugin

        assert "execute_go_live" in marketer_plugin().manifest.tools

    def test_brief_documents_the_executor_step(self) -> None:
        from chorus_employee.marketer import MARKETER_BRIEF

        assert "execute_go_live" in MARKETER_BRIEF
