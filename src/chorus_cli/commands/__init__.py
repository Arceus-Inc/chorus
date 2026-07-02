"""The console command table. Importing this package registers every verb into REGISTRY and
applies the aliases; the console dispatches through it."""

from __future__ import annotations

# Import each group for its `@REGISTRY.command` side effects (original order = help listing order).
from chorus_cli.commands import (  # noqa: F401
    approvals,
    budgets,
    coordination,
    dod,
    kernel,
    minimal,
    routines,
    tasks,
    workforce,
)
from chorus_cli.commands._base import REGISTRY

# Aliases, applied after every command is registered.
REGISTRY.alias("?", of="help")
REGISTRY.alias("exit", of="quit")
REGISTRY.alias("budgets", of="budget")
REGISTRY.alias("approvals", of="approval")
REGISTRY.alias("routines", of="routine")

__all__ = ["REGISTRY"]
