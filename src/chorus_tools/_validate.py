"""Shared boundary-validation helpers for the tool value objects.

One ``require`` instead of the identical ``_require`` that had been copied into both the cms and the
delivery ``_types`` modules.
"""

from __future__ import annotations


def require(value: str, name: str) -> None:
    """Raise ``ValueError`` naming ``name`` unless ``value`` is a non-blank string."""
    if not value or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


__all__ = ["require"]
