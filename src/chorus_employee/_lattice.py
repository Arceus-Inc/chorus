"""Lattice directives — shared by every employee that carries lattice tools."""

from __future__ import annotations

from lattice.directive import LATTICE_CONSOLIDATE_DIRECTIVE, LATTICE_CONTEXT_DIRECTIVE

LATTICE_DIRECTIVES_BLOCK = (
    "\n\n"
    + LATTICE_CONTEXT_DIRECTIVE
    + "\n"
    + LATTICE_CONSOLIDATE_DIRECTIVE
)

__all__ = ["LATTICE_DIRECTIVES_BLOCK"]
