"""The canonical cross-child contract — module map · public API · ownership (spec 15 §4.1).

``AGENTS.md`` is the single object that defines what "one coherent deliverable" means: the files the
package will contain, the exact symbols its ``__init__`` must export, and which child owns which file.
The manager authors it at decompose; the deterministic coherence checker reconciles the merged tree to
it at the manager's integrate beat. This module is the codec both sides share, so the on-disk shape
cannot drift between writer and reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_BACKTICK = re.compile(r"`([^`]+)`")
_OWNER = re.compile(r"`([^`]+)`\s*(?:->|→)\s*(\S+)")


@dataclass(frozen=True)
class AgentsMd:
    """The deliverable's declared public surface (the cross-child contract)."""

    modules: tuple[str, ...] = ()
    public_api: tuple[str, ...] = ()
    ownership: dict[str, str] = field(default_factory=dict)  # repo-relative path -> employee id
    # module path -> the sibling module paths it imports (the build-order DAG the kernel fans out on).
    dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @staticmethod
    def parse(text: str) -> AgentsMd:
        """Parse the four sections; forgiving of blank lines, missing sections, and ``->``/``→``."""
        sections = _split_sections(text)
        modules = tuple(
            path for ln in sections.get("module map", []) if (path := _first_backtick(ln)) is not None
        )
        public = tuple(
            sym for ln in sections.get("public api", []) if (sym := _first_backtick(ln)) is not None
        )
        ownership: dict[str, str] = {}
        for ln in sections.get("ownership", []):
            owner = _OWNER.search(ln)
            if owner is not None:
                ownership[owner.group(1)] = owner.group(2)
        # Dependencies: ``- `model.py` -> `ingest.py`, `types.py``  (a module and the modules it imports).
        dependencies: dict[str, tuple[str, ...]] = {}
        for ln in sections.get("dependencies", []) + sections.get("build order", []):
            backticks = _BACKTICK.findall(ln)
            if len(backticks) >= 2:
                dependencies[backticks[0]] = tuple(backticks[1:])
        return AgentsMd(
            modules=modules, public_api=public, ownership=ownership, dependencies=dependencies
        )

    def render(self) -> str:
        """Render the contract back to canonical markdown (round-trips through :meth:`parse`)."""
        lines = ["# AGENTS.md", "", "## Module map"]
        lines += [f"- `{m}` — " for m in self.modules]
        lines += ["", "## Public API"]
        lines += [f"- `{s}`" for s in self.public_api]
        lines += ["", "## Ownership"]
        lines += [f"- `{path}` -> {owner}" for path, owner in self.ownership.items()]
        lines += ["", "## Dependencies"]
        lines += [
            f"- `{mod}` -> {', '.join(f'`{d}`' for d in deps)}"
            for mod, deps in self.dependencies.items()
        ]
        return "\n".join(lines) + "\n"


def _split_sections(text: str) -> dict[str, list[str]]:
    """Bucket ``- `` list items under their preceding ``## `` heading (lower-cased)."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            current = line[3:].strip().lower()
            out[current] = []
        elif current is not None and line.strip().startswith("-"):
            out[current].append(line)
    return out


def _first_backtick(line: str) -> str | None:
    match = _BACKTICK.search(line)
    return match.group(1) if match is not None else None


__all__ = ["AgentsMd"]
