"""Composition root — adapt chorus episodic memory to lattice ports.

Boundary: chorus owns company paths + episodic store; lattice owns semantic
consolidation. Procedural skills use Chorus ``SkillStore`` / ``skill_manage`` —
do not enable lattice overlay patches for the chorus path.
"""

from __future__ import annotations

from pathlib import Path

from lattice.compose import build_default
from lattice.contracts.episodic import RawEpisode
from lattice.facade import Lattice

from chorus.ledger import Ledger
from chorus.memory import EpisodicStore, SprintDelta


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
    ledger: Ledger,
    *,
    min_new_episodes: int | None = None,
    min_cluster_size: int | None = None,
    canonical_skills_root: str | Path | None = None,
) -> Lattice:
    """Wire lattice to a company: episodes from the shared-schema store, files under ``lattice/``.

    Overlay patches stay off — procedural writes go through ``skill_manage``.
    ``canonical_skills_root`` is still passed so habit *validation* inside
    SkillManager can discover role skill slugs.
    """
    root = Path(company_root)
    store = EpisodicStore(ledger)
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


def write_lattice_error(harness_root: Path, *, site: str, error: Exception) -> None:
    """Leave a durable breadcrumb when an advisory lattice step fails.

    Lattice is advisory by design — a failure must never block the beat — but an invisible failure
    means consolidation silently stops forever. This file is the observable middle ground: cheap,
    best-effort, overwritten per occurrence, and greppable by an operator or a probe.
    """
    import json
    from datetime import UTC, datetime

    try:
        harness = Path(harness_root) / ".harness"
        harness.mkdir(parents=True, exist_ok=True)
        (harness / "lattice-error.json").write_text(
            json.dumps(
                {
                    "site": site,
                    "error": f"{type(error).__name__}: {error}",
                    "at": datetime.now(tz=UTC).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        return  # the breadcrumb itself must never raise


__all__ = [
    "ChorusEpisodicReader",
    "build_lattice_for_chorus",
    "write_lattice_error",
]
