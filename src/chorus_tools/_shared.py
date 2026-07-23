"""Small helpers shared across chorus_tools — one copy instead of a per-tool paste."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dream.contracts.tool import ToolResult


def write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as pretty-printed JSON (indent=2, trailing newline)."""
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def rejected(tool: str, message: str, *, safe_retry: str) -> ToolResult:
    """The uniform invalid-input refusal a deterministic scanner returns (teaches the retry)."""
    return ToolResult(
        content=f"{tool} rejected: {message}",
        is_error=True,
        metadata={
            "root_cause": message,
            "safe_retry": safe_retry,
            "stop_condition": "the tool input was invalid",
        },
    )


__all__ = ["rejected", "write_json"]
