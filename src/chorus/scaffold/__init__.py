"""Stack-detected project scaffolding — lay down the manifest before fan-out (the manifest-as-module fix)."""

from chorus.scaffold._scaffold import detect_stack, scaffold_command, scaffold_if_missing

__all__ = ["detect_stack", "scaffold_command", "scaffold_if_missing"]
