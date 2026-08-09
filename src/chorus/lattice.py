"""Public composition for exact Lattice context-outcome edges."""

from __future__ import annotations

from dataclasses import dataclass

from lattice.facade import Lattice


@dataclass(frozen=True, slots=True)
class LatticeRuntime:
    """The one public PostgreSQL-backed Lattice shared by harnesses and scheduler."""

    lattice: Lattice


__all__ = ["LatticeRuntime"]
