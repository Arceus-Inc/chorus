"""Built-in Definition-of-Done verifier commands.

These helpers return shell-safe commands for objective DoD checks that live in Chorus itself, not in
the repository being verified. The scheduler still runs them with ``cwd`` set to the worktree under
test, so the checks inspect the product repo without seeding harness-owned files into it.
"""

from __future__ import annotations

import subprocess
import sys


def module_command(module: str, *args: str) -> str:
    """Return a shell-safe command that runs a Chorus verifier module."""
    return subprocess.list2cmdline([sys.executable, "-m", module, *args])


def stack_gate_command() -> str:
    """The stack-aware product gate command."""
    return module_command("chorus.verifiers.stack_gate")


def spec_gate_command(plan_file: str = "plan.md") -> str:
    """The PM/spec artifact gate command."""
    return module_command("chorus.verifiers.spec_gate", plan_file)


__all__ = ["module_command", "spec_gate_command", "stack_gate_command"]