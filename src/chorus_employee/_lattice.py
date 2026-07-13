"""Lattice directives — shared by every employee that carries lattice tools."""

from __future__ import annotations

import json
from pathlib import Path

from lattice.directive import LATTICE_CONSOLIDATE_DIRECTIVE, LATTICE_CONTEXT_DIRECTIVE

# Bundled agent skills — materialized into each worktree's ``.harness/skills/`` at beat time.
LATTICE_SKILLS_ROOT = Path(__file__).resolve().parent / "_lattice_skills"

LATTICE_DIRECTIVES_BLOCK = "\n\n" + LATTICE_CONTEXT_DIRECTIVE + "\n" + LATTICE_CONSOLIDATE_DIRECTIVE

LATTICE_BEAT_START_HEADER = "## Lattice consolidation (auto — gate was open last beat)\n"

LATTICE_BEAT_START_FOOTER = (
    "FIRST this beat (before other task work): load skill `lattice-consolidate`, "
    "call `lattice_packet()`, `recall(query)` + `get_run(run_id)` per cited beat, "
    "then `lattice_apply` with ≤10 patterns and `skill_manage(evolve|patch)` for procedures."
)


def read_lattice_consolidation_push(harness_dir: Path) -> str:
    """Read the prior beat's gate-open teaser for injection at materialize (integration §4.4 B)."""
    path = harness_dir / ".harness" / "lattice-beat-end.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if payload.get("gate_open") is not True:
        return ""
    teaser = str(payload.get("teaser", "")).strip()
    if not teaser:
        return ""
    return f"{teaser}\n{LATTICE_BEAT_START_FOOTER}"


__all__ = [
    "LATTICE_BEAT_START_FOOTER",
    "LATTICE_BEAT_START_HEADER",
    "LATTICE_DIRECTIVES_BLOCK",
    "LATTICE_SKILLS_ROOT",
    "read_lattice_consolidation_push",
]
