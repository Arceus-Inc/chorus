"""The console exposes no authority-bypassing ``decompose`` command."""

from __future__ import annotations

import pytest

from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def test_legacy_decompose_command_is_not_registered() -> None:
    assert REGISTRY.get("decompose") is None
