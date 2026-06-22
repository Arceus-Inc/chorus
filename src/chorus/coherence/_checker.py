"""Deterministic coherence checks reconciled to AGENTS.md (spec 15 §4.3).

Pure: filesystem + ``ast`` only, no imports executed. Each check defines one way the merged tree can
diverge from the contract — the symptoms seen 3-of-3 in live ``--org`` runs (split-brain done):

- ``missing_module`` — a declared module path is absent.
- ``duplicate_symbol`` — a declared public symbol is defined in more than one module (two Trainers).
- ``missing_export`` — ``__init__`` does not export a declared public symbol (empty/wrong surface).
- ``orphan_module`` — a declared non-``__init__`` module is imported by nothing (dead ``loss.py``).

Importability ("builds + imports in a clean env") is the CLI's subprocess check, not a static one.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from chorus.coherence._agents_md import AgentsMd


@dataclass(frozen=True)
class CoherenceViolation:
    """One way the merged tree diverges from the AGENTS.md contract."""

    code: str
    message: str
    path: str | None = None


def check_coherence(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    """Every static coherence violation of ``doc`` by the tree under ``root`` (empty list = coherent)."""
    return (
        _missing_modules(root, doc)
        + _duplicate_symbols(root, doc)
        + _missing_exports(root, doc)
        + _orphan_modules(root, doc)
    )


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None


def _top_level_defs(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _missing_modules(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    return [
        CoherenceViolation("missing_module", f"declared module is absent: {m}", m)
        for m in doc.modules
        if not (root / m).is_file()
    ]


def _duplicate_symbols(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    wanted = {s.rsplit(".", 1)[-1] for s in doc.public_api}
    definers: dict[str, list[str]] = {}
    for m in doc.modules:
        path = root / m
        if path.name == "__init__.py" or not path.is_file():
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for name in _top_level_defs(tree) & wanted:
            definers.setdefault(name, []).append(m)
    return [
        CoherenceViolation("duplicate_symbol", f"public symbol {name!r} defined in {mods}")
        for name, mods in definers.items()
        if len(mods) > 1
    ]


def _init_bound_names(root: Path, doc: AgentsMd) -> set[str]:
    init = next((root / m for m in doc.modules if m.endswith("__init__.py")), None)
    if init is None or not init.is_file():
        return set()
    tree = _parse(init)
    if tree is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _missing_exports(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    bound = _init_bound_names(root, doc)
    return [
        CoherenceViolation("missing_export", f"__init__ does not export declared symbol: {s}", s)
        for s in doc.public_api
        if s.rsplit(".", 1)[-1] not in bound
    ]


def _imported_module_leaves(root: Path, doc: AgentsMd) -> set[str]:
    """The final dotted component of every module any package file imports (``pkg.core`` → ``core``)."""
    leaves: set[str] = set()
    for m in doc.modules:
        tree = _parse(root / m)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                leaves.add(node.module.rsplit(".", 1)[-1])
            elif isinstance(node, ast.Import):
                leaves |= {alias.name.rsplit(".", 1)[-1] for alias in node.names}
    return leaves


def _orphan_modules(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    imported = _imported_module_leaves(root, doc)
    out: list[CoherenceViolation] = []
    for m in doc.modules:
        if m.endswith("__init__.py"):
            continue
        leaf = Path(m).stem  # `pkg/loss.py` -> `loss`
        if leaf not in imported:
            out.append(CoherenceViolation("orphan_module", f"module imported by nothing: {m}", m))
    return out


__all__ = ["CoherenceViolation", "check_coherence"]
