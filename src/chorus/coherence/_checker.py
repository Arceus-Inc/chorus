"""Deterministic coherence checks reconciled to AGENTS.md (spec 15 §4.3).

Pure: filesystem + ``ast`` only, no imports executed. Each check defines one way the merged tree can
diverge from the contract — the symptoms seen 3-of-3 in live ``--org`` runs (split-brain done):

- ``missing_module`` — a declared module path is absent.
- ``duplicate_symbol`` — a public symbol is defined in more than one module (two Trainers).
- ``missing_export`` — ``__init__`` does not export a declared public symbol (empty/wrong surface).
- ``orphan_module`` — a declared non-``__init__`` module is imported by nothing (dead ``loss.py``).

Importability ("builds + imports in a clean env") is the CLI's subprocess check, not a static one.

Placeholder-aware: if the manager left ``AGENTS.md`` as the seeded skeleton (it still contains the
``<package>`` / ``<Symbol>`` placeholders), the DECLARED checks (missing-module/export, orphan) cannot
run — there is no real contract to reconcile to. In that case only the STRUCTURAL split-brain check
runs (a public symbol that ``__init__`` re-exports must not be defined in two sibling modules), so the
gate never false-blocks coherent code yet still catches a genuine rival. A filled contract runs
everything (stricter).
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

from chorus.coherence._agents_md import AgentsMd


@dataclass(frozen=True)
class CoherenceViolation:
    """One way the merged tree diverges from the AGENTS.md contract."""

    code: str
    message: str
    path: str | None = None


def is_placeholder(doc: AgentsMd) -> bool:
    """True when the contract is still the seeded skeleton (unfilled by the manager)."""
    return any("<" in m for m in doc.modules) or any("<" in s for s in doc.public_api) or (
        not doc.modules and not doc.public_api
    )


def authored_contract(worktree: Path) -> str | None:
    """Return ``worktree/AGENTS.md`` content iff it is an authored (non-placeholder) contract, else ``None``.

    The single read both the ``decompose`` gate (refuse to fan out before the manager has authored the
    contract — spec 15 §4.1) and the per-beat ingestion marker (record which contract an engineer beat
    actually branched off — spec 15 §4.2) reconcile against, so "authored" means the same thing to both:
    a real module map / public API, not the seeded ``<package>`` skeleton.
    """
    path = worktree / "AGENTS.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return None if is_placeholder(AgentsMd.parse(text)) else text


def contract_sha(content: str) -> str:
    """A short stable identity for a contract's CONTENT — the ``vN`` both publish and ingest record.

    Hashing the content (not the git commit) lets a query correlate "manager published contract X" with
    "engineer beat Y ingested contract X" even though they land on different commits (spec 15 §4.2).
    """
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


def check_coherence(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    """Every static coherence violation of ``doc`` by the tree under ``root`` (empty list = coherent).

    With a filled contract, reconcile the tree to it. With an unfilled (placeholder) contract, run only
    the contract-free structural split-brain check so coherent code is never spuriously blocked.
    """
    if is_placeholder(doc):
        return _structural_duplicate_symbols(root)
    wanted = {s.rsplit(".", 1)[-1] for s in doc.public_api}
    return (
        _missing_modules(root, doc)
        + _duplicate_symbols(root, doc.modules, wanted)
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


def _bound_names(tree: ast.Module) -> set[str]:
    """Names an ``__init__`` makes part of its surface: imports, top-level defs, assignments."""
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


def _is_test_module(module: str) -> bool:
    """A test file is never imported (the runner discovers it) and is an implementation detail of a
    subtask, not part of the cross-child SOURCE contract — so coherence does not reconcile it."""
    norm = module.replace("\\", "/")
    name = norm.rsplit("/", 1)[-1]
    return (
        norm.startswith(("tests/", "test/"))
        or "/tests/" in norm
        or "/test/" in norm
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _is_entrypoint(root: Path, module: str) -> bool:
    """An entry-point module (a CLI / ``__main__``) is reached by being RUN, not imported, so it is not
    an orphan even when no sibling imports it (the prefrank ``cli.py`` false positive)."""
    if Path(module).name in {"__main__.py", "cli.py"}:
        return True
    tree = _parse(root / module)
    if tree is None:
        return False
    return any(  # a top-level ``if __name__ == "__main__":`` guard marks a runnable entry point
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        for node in tree.body
    )


def _missing_modules(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    return [
        CoherenceViolation("missing_module", f"declared module is absent: {m}", m)
        for m in doc.modules
        if not _is_test_module(m) and not (root / m).is_file()
    ]


def _duplicate_symbols(
    root: Path, modules: tuple[str, ...], wanted: set[str]
) -> list[CoherenceViolation]:
    """A name in ``wanted`` defined as a top-level def/class in more than one non-``__init__`` module."""
    definers: dict[str, list[str]] = {}
    for module in modules:
        path = root / module
        if path.name == "__init__.py" or not path.is_file():
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for name in _top_level_defs(tree) & wanted:
            definers.setdefault(name, []).append(module)
    return [
        CoherenceViolation("duplicate_symbol", f"public symbol {name!r} defined in {mods}")
        for name, mods in definers.items()
        if len(mods) > 1
    ]


def _structural_duplicate_symbols(root: Path) -> list[CoherenceViolation]:
    """Contract-free split-brain check: for each discovered package, a name its ``__init__`` re-exports
    must not be defined in two sibling modules. Internal name collisions (not re-exported) are ignored,
    so this does not false-block legitimately-distinct same-named internals."""
    out: list[CoherenceViolation] = []
    for pkg in _discover_packages(root):
        init = root / pkg / "__init__.py"
        tree = _parse(init)
        exported = _bound_names(tree) if tree is not None else set()
        modules = tuple(
            f"{pkg}/{p.name}"
            for p in sorted((root / pkg).glob("*.py"))
            if p.name != "__init__.py"
        )
        out += _duplicate_symbols(root, modules, exported)
    return out


def _discover_packages(root: Path) -> list[str]:
    """Top-level importable packages in the tree (a directory with an ``__init__.py``)."""
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").is_file()
    )


def _init_bound_names(root: Path, doc: AgentsMd) -> set[str]:
    init = next((root / m for m in doc.modules if m.endswith("__init__.py")), None)
    if init is None or not init.is_file():
        return set()
    tree = _parse(init)
    return _bound_names(tree) if tree is not None else set()


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
    for module in doc.modules:
        tree = _parse(root / module)
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
    for module in doc.modules:
        # ``__init__`` re-exports (never an orphan); test files are discovered, not imported; an entry
        # point (CLI / ``__main__``) is run, not imported — none of these are dead code.
        if (
            module.endswith("__init__.py")
            or _is_test_module(module)
            or _is_entrypoint(root, module)
        ):
            continue
        leaf = Path(module).stem  # `pkg/loss.py` -> `loss`
        if leaf not in imported:
            out.append(CoherenceViolation("orphan_module", f"module imported by nothing: {module}", module))
    return out


__all__ = ["CoherenceViolation", "check_coherence", "is_placeholder"]
