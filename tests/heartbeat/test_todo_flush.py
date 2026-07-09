"""Pre-beat-end TODO flush nudge file (OpenClaw-style budget warning)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.heartbeat._todo_flush import (
    TODO_FLUSH_REMAINING_FRACTION,
    clear_todo_flush_nudge,
    format_todo_flush_banner,
    nudge_path_in,
    read_todo_flush_nudge,
    write_todo_flush_nudge,
)

pytestmark = pytest.mark.unit


def test_write_read_and_clear_nudge(tmp_path: Path) -> None:
    armed = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    write_todo_flush_nudge(
        tmp_path,
        timeout_s=360.0,
        remaining_s=36.0,
        armed_at=armed,
    )

    nudge = read_todo_flush_nudge(tmp_path)
    assert nudge is not None
    assert nudge.timeout_s == 360.0
    assert nudge.remaining_s == 36.0
    assert nudge.armed_at == armed.isoformat()
    assert nudge_path_in(tmp_path).is_file()

    clear_todo_flush_nudge(tmp_path)
    assert read_todo_flush_nudge(tmp_path) is None
    assert not nudge_path_in(tmp_path).exists()


def test_read_missing_nudge_returns_none(tmp_path: Path) -> None:
    assert read_todo_flush_nudge(tmp_path) is None


def test_format_banner_uses_remaining_seconds() -> None:
    banner = format_todo_flush_banner(remaining_s=36.4)
    assert "~36s remaining" in banner
    assert "todo_write" in banner
    assert "<10% budget" in banner


def test_remaining_fraction_is_ten_percent() -> None:
    assert TODO_FLUSH_REMAINING_FRACTION == 0.10
