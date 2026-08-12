"""Lattice wake helpers — skills own standing craft; TCP carries the gate teaser only."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from chorus.context._packet import LatticeWake

# Bundled agent skills — materialized into each worktree's ``.harness/skills/`` at beat time.
LATTICE_SKILLS_ROOT = Path(__file__).resolve().parent / "_lattice_skills"


@dataclass(frozen=True)
class _LatticeBeatEndRecord:
    gate_open: bool
    teaser: str


def read_lattice_wake(harness_dir: Path) -> LatticeWake | None:
    """Read the prior beat's gate-open teaser for the TCP lattice_wake field."""
    path = harness_dir / ".harness" / "lattice-beat-end.json"
    if not path.is_file():
        return None
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    record = _parse_beat_end(raw)
    if record is None or not record.gate_open or not record.teaser:
        return None
    return LatticeWake(gate_open=True, teaser=record.teaser)


def _parse_beat_end(raw: object) -> _LatticeBeatEndRecord | None:
    if not isinstance(raw, Mapping):
        return None
    gate = raw.get("gate_open")
    teaser_raw = raw.get("teaser", "")
    if not isinstance(teaser_raw, str):
        return None
    return _LatticeBeatEndRecord(gate_open=gate is True, teaser=teaser_raw.strip())


__all__ = [
    "LATTICE_SKILLS_ROOT",
    "read_lattice_wake",
]
