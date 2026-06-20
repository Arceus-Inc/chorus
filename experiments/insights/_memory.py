"""Memory-store view — the append-only episodic trace, one record per beat (spec 07 §3).

chorus writes a single ``{scope}/{run_id}.md`` per beat with YAML frontmatter (``metadata`` carries
``employee_id``/``task_id``/``intent``/``outcome``/``score``/``files_touched``). This view reads those
records straight off disk — the same files dream's ``MemoryStore`` reads back — so you can see what the
workforce actually remembered, without a model in the loop.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from experiments.insights import _render as r
from experiments.insights._sources import ExperimentSources


@dataclass(frozen=True)
class MemoryRecordView:
    """One parsed on-disk memory record (the fields the writer stamps into frontmatter)."""

    run_id: str
    scope: str
    employee_id: str
    task_id: str
    kind: str
    intent: str
    outcome: str
    score: float | None
    files_touched: int
    artifacts: int
    created_at: str


def render(sources: ExperimentSources) -> str:
    """The memory store as a rollup (per scope / per employee) + a per-record table."""
    if sources.memory_dir is None:
        return r.header("MEMORY STORE") + "\n  (no memory/ store found next to the ledger)"

    records = sorted(load(sources.memory_dir), key=lambda m: m.created_at)
    if not records:
        return r.header("MEMORY STORE") + f"\n  (empty store at {sources.memory_dir})"

    by_scope = Counter(m.scope for m in records)
    by_employee = Counter(m.employee_id for m in records)
    scored = [m.score for m in records if m.score is not None]
    avg = sum(scored) / len(scored) if scored else 0.0

    headers = ("run", "employee", "task", "scope", "score", "kind", "files", "intent")
    rows = [
        (
            r.truncate(m.run_id, 14),
            m.employee_id or r.paint("—", "grey"),
            r.truncate(m.task_id, 14),
            m.scope,
            f"{m.score:.2f}" if m.score is not None else r.paint("—", "grey"),
            m.kind,
            str(m.files_touched) if m.files_touched else r.paint("0", "grey"),
            r.truncate(m.intent, 40),
        )
        for m in records
    ]
    return "\n".join(
        [
            r.header("MEMORY STORE"),
            r.kv("records", f"{len(records)}  ·  avg score {avg:.2f}"),
            r.kv("scopes", "  ".join(f"{name}={n}" for name, n in by_scope.most_common())),
            r.kv("authors", "  ".join(f"{name}={n}" for name, n in by_employee.most_common())),
            "",
            r.table(headers, rows),
        ]
    )


def load(memory_dir: Path) -> list[MemoryRecordView]:
    """Parse every ``{scope}/{run_id}.md`` record under ``memory_dir``."""
    return [_parse(path) for path in sorted(memory_dir.glob("*/*.md"))]


def _parse(path: Path) -> MemoryRecordView:
    meta = _frontmatter(path)
    score = meta.get("score")
    return MemoryRecordView(
        run_id=str(meta.get("run_id") or path.stem),
        scope=str(meta.get("scope") or path.parent.name),
        employee_id=str(meta.get("employee_id") or ""),
        task_id=str(meta.get("task_id") or ""),
        kind=str(meta.get("kind") or "sprint_delta"),
        intent=str(meta.get("intent") or ""),
        outcome=str(meta.get("outcome") or ""),
        score=float(score) if isinstance(score, (int, float)) else None,
        files_touched=len(meta.get("files_touched") or ()),
        artifacts=len(meta.get("artifacts") or ()),
        created_at=str(meta.get("created_at") or ""),
    )


def _frontmatter(path: Path) -> dict[str, Any]:
    """The ``metadata`` block of a record's YAML frontmatter (empty dict if unparseable)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), len(lines))
    header = yaml.safe_load("\n".join(lines[1:end])) or {}
    meta = header.get("metadata") if isinstance(header, dict) else None
    return meta if isinstance(meta, dict) else {}


__all__ = ["MemoryRecordView", "load", "render"]
