"""The single command registry the console dispatches through (one instance, shared by every
command module so `@REGISTRY.command` at import time populates one table)."""

from __future__ import annotations

from chorus_cli._registry import CommandRegistry

REGISTRY = CommandRegistry()

__all__ = ["REGISTRY"]
