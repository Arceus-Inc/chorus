"""Shared employee skills merged into every role that materializes a skills_root."""

from __future__ import annotations

from pathlib import Path

SHARED_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"

__all__ = ["SHARED_SKILLS_ROOT"]
