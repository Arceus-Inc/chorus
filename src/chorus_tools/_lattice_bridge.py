"""Composition root — adapt chorus episodic memory to lattice ports.

Boundary: chorus owns company paths + episodic store; lattice owns semantic
consolidation. Procedural skills use Chorus ``SkillStore`` / ``skill_manage`` —
do not enable lattice overlay patches for the chorus path.
"""

from __future__ import annotations

from pathlib import Path

from chorus.memory import EpisodicStore, SprintDelta
from lattice.compose import build_default
from lattice.contracts.episodic import EpisodicReader, RawEpisode
from lattice.facade import Lattice


class ChorusEpisodicReader:
    """Adapt chorus ``EpisodicStore`` to lattice ``EpisodicReader``."""

    def __init__(self, store: EpisodicStore) -> None:
        self._store = store

    def records_for(self, employee_id: str) -> tuple[RawEpisode, ...]:
        return tuple(_to_raw(delta) for delta in self._store.records_for(employee_id))

    def count_for(self, employee_id: str) -> int:
        return len(self._store.records_for(employee_id))


def _to_raw(delta: SprintDelta) -> RawEpisode:
    return RawEpisode(
        run_id=delta.run_id,
        task_id=delta.task_id,
        employee_id=delta.employee_id,
        role=delta.role,
        scope=delta.scope,
        intent=delta.intent,
        outcome=delta.outcome,
        score=delta.score,
        created_at=delta.created_at,
        recorded_at=delta.recorded_at,
        artifacts=delta.artifacts,
        files_touched=delta.files_touched,
        body=delta.body,
    )


def build_lattice_for_chorus(
    company_root: str | Path,
    *,
    min_new_episodes: int | None = None,
    min_cluster_size: int | None = None,
    canonical_skills_root: str | Path | None = None,
) -> Lattice:
    """Wire lattice to a chorus company directory (``memory/`` + ``lattice/``).

    Overlay patches stay off — procedural writes go through ``skill_manage``.
    ``canonical_skills_root`` is still passed so habit *validation* inside
    SkillManager can discover role skill slugs.
    """
    root = Path(company_root)
    store = EpisodicStore(root / "memory")
    kwargs: dict[str, object] = {
        "consolidated_root": root / "lattice",
        "episodes": ChorusEpisodicReader(store),
        "enable_patches": False,
    }
    if min_new_episodes is not None:
        kwargs["min_new_episodes"] = min_new_episodes
    if min_cluster_size is not None:
        kwargs["min_cluster_size"] = min_cluster_size
    if canonical_skills_root is not None:
        kwargs["canonical_skills_root"] = Path(canonical_skills_root)
    return build_default(**kwargs)  # type: ignore[arg-type]


__all__ = [
    "ChorusEpisodicReader",
    "build_lattice_for_chorus",
]
