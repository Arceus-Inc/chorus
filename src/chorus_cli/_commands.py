"""Back-compat shim — the console command table moved to :mod:`chorus_cli.commands`.

``REGISTRY`` is re-exported so existing imports (`from chorus_cli._commands import REGISTRY`)
keep working."""

from __future__ import annotations

from chorus_cli.commands import REGISTRY

__all__ = ["REGISTRY"]
