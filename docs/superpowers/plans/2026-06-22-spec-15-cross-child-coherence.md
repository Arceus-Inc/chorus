# Spec-15 — Cross-child coherence via AGENTS.md — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `--org` build of a multi-module library either land a single coherent public surface, or end `blocked` with a specific coherence reason — never a silent split-brain `done`.

**Architecture:** The manager authors a canonical `AGENTS.md` (module map · public API · ownership) at decompose. A deterministic `python -m chorus.coherence` checker reconciles the merged tree to that contract (declared modules exist, no duplicate public symbol, `__init__` exports the declared API, no orphan modules, package imports clean). The manager's integrate is gated on that checker via a `Verifier.command` DoD — the existing `_integrate_floor_verdict` kernel machinery already runs a manager's objective `Command` DoD against the integrated worktree and blocks/loops on failure, so chorus-side wiring is small. The dream prevent-layer wires dream's dormant `run_orientation` + `session_start_findings` so every engineer beat reads `AGENTS.md` before writing.

**Tech Stack:** Python 3.13, `ast` (static analysis), pytest, the chorus ledger/scheduler, dream's harness/session engine.

---

## Key seams (verified at `48ca918`)

- `src/chorus/outcomes/_verifier.py` — `Verifier.command(cmd, artifact_class=...)` already exists. **No new DoDKind needed** — the coherence DoD is a `Command`.
- `src/chorus/heartbeat/_scheduler.py:640,719` — `_integrate_floor_verdict(task_id, verifier, beat_runner)` runs the parent's `Command` DoD via `verification_steps()` in the integrator's worktree (= company main after children merge); returns `False` → the integrate parks `blocked`; the adaptive loop (`max_integrate_iterations`, `_maybe_cap_integrate`) re-dispatches the manager to reconcile. **This is the gate; we only need the manager task to carry a coherence Command DoD.**
- `src/chorus/lifecycle/_decompose.py:83` — `decompose(...)` is where the manager fans out; AGENTS.md authoring is the manager's responsibility (it has the worktree + the plan), surfaced via the manager brief + a write at decompose time.
- `src/chorus_employee/manager/_lander.py` — `ManagerLander.land` records the `subtree` artifact; it only runs once the integrate beat passed (which now includes the coherence floor), so no change is strictly required, but it records the coherence verdict in the artifact for the audit trail.
- dream (`/Users/divyansh/Harness/src/dream`): `services/session_guard.py::session_start_findings(paths) -> list[Finding]` and `engine/_orientation.py::run_orientation(OrientationConfig) -> OrientationBrief` are implemented but **dormant**; `config/paths.py::DreamPaths.agents_md` exists. `SessionConfig.orientation` defaults to `None`; wiring it on at `_factory.py::_build_session_engine` / `make_session_config` activates the `orienting` state in `engine/_session.py:515-564`.

## File structure

**chorus (new package `src/chorus/coherence/`):**
- `__init__.py` — public exports (`AgentsMd`, `check_coherence`, `CoherenceViolation`).
- `_agents_md.py` — the `AgentsMd` dataclass + `parse()` / `render()` codec.
- `_checker.py` — pure check functions → `list[CoherenceViolation]`.
- `__main__.py` — CLI: `python -m chorus.coherence [--root .] [--agents AGENTS.md]`; prints violations, exits 1 if any.
- `tests/coherence/test_agents_md.py`, `tests/coherence/test_checker.py`, `tests/coherence/test_cli.py`.

**chorus (modify):**
- `src/chorus/lifecycle/_decompose.py` — write `AGENTS.md` skeleton at decompose (deterministic seed; the manager fills it).
- `src/chorus_employee/manager/_brief.py` — instruct the manager to author/maintain `AGENTS.md`.
- the goal/manager DoD wiring (standup harness `standup-app/run.py` `_pin_objective_dod` + a `_objective_goal_dod`) — pin the goal's rollup DoD to `Verifier.command("python -m chorus.coherence")`.
- `src/chorus_employee/manager/_lander.py` — record the coherence verdict in the subtree artifact.

**dream (modify):**
- `src/dream/__init__.py` — export `run_orientation`, `OrientationConfig`, `OrientationBrief`, `session_start_findings`, `Finding`, `has_blocking`, `DreamPaths`.
- `src/dream/_factory.py` — `build_harness(..., orientation: bool = False)`; build `OrientationConfig` whose `gather` reads `AGENTS.md` + `session_start_findings`; thread to `SessionConfig`.

**chorus (modify) to call dream:**
- `src/chorus_harness/_factory.py` — pass `orientation=True` into `dream.build_harness` for engineer beats.

---

## Task 1: `AgentsMd` codec — parse/render the contract

**Files:**
- Create: `src/chorus/coherence/__init__.py`
- Create: `src/chorus/coherence/_agents_md.py`
- Test: `tests/coherence/test_agents_md.py`

The contract is markdown with three fixed sections. Format (what the manager writes, what we parse):

```markdown
# AGENTS.md

## Module map
- `dpo_tune/__init__.py` — package entry; re-exports the public API
- `dpo_tune/trainer.py` — Trainer.fit()
- `dpo_tune/loss.py` — dpo_loss()

## Public API
- `dpo_tune.Trainer`
- `dpo_tune.dpo_loss`

## Ownership
- `dpo_tune/trainer.py` -> ada
- `dpo_tune/loss.py` -> bo
```

- [ ] **Step 1: Write the failing test**

```python
# tests/coherence/test_agents_md.py
"""AGENTS.md codec — the canonical cross-child contract (spec 15 §4.1)."""
from __future__ import annotations

import pytest

from chorus.coherence import AgentsMd

pytestmark = pytest.mark.unit

_SAMPLE = """# AGENTS.md

## Module map
- `dpo_tune/__init__.py` — package entry; re-exports the public API
- `dpo_tune/trainer.py` — Trainer.fit()

## Public API
- `dpo_tune.Trainer`
- `dpo_tune.dpo_loss`

## Ownership
- `dpo_tune/trainer.py` -> ada
- `dpo_tune/loss.py` -> bo
"""


def test_parse_extracts_the_three_sections() -> None:
    doc = AgentsMd.parse(_SAMPLE)
    assert doc.modules == ("dpo_tune/__init__.py", "dpo_tune/trainer.py")
    assert doc.public_api == ("dpo_tune.Trainer", "dpo_tune.dpo_loss")
    assert doc.ownership == {"dpo_tune/trainer.py": "ada", "dpo_tune/loss.py": "bo"}


def test_render_round_trips() -> None:
    doc = AgentsMd.parse(_SAMPLE)
    assert AgentsMd.parse(doc.render()) == doc


def test_parse_is_forgiving_of_blank_and_missing_sections() -> None:
    doc = AgentsMd.parse("# AGENTS.md\n\n## Public API\n- `pkg.Thing`\n")
    assert doc.public_api == ("pkg.Thing",)
    assert doc.modules == ()
    assert doc.ownership == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/coherence/test_agents_md.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'chorus.coherence'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/chorus/coherence/_agents_md.py
"""The canonical cross-child contract — module map · public API · ownership (spec 15 §4.1)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_BACKTICK = re.compile(r"`([^`]+)`")
_OWNER = re.compile(r"`([^`]+)`\s*(?:->|→)\s*(\S+)")


@dataclass(frozen=True)
class AgentsMd:
    """The deliverable's declared public surface, authored by the manager at decompose."""

    modules: tuple[str, ...] = ()
    public_api: tuple[str, ...] = ()
    ownership: tuple[tuple[str, str], ...] = ()  # (path, owner) pairs; frozen for hashing

    @property
    def ownership_map(self) -> dict[str, str]:
        return dict(self.ownership)

    @staticmethod
    def parse(text: str) -> AgentsMd:
        sections = _split_sections(text)
        modules = tuple(_first_backtick(ln) for ln in sections.get("module map", []) if _first_backtick(ln))
        public = tuple(_first_backtick(ln) for ln in sections.get("public api", []) if _first_backtick(ln))
        owners: list[tuple[str, str]] = []
        for ln in sections.get("ownership", []):
            m = _OWNER.search(ln)
            if m is not None:
                owners.append((m.group(1), m.group(2)))
        return AgentsMd(modules=modules, public_api=public, ownership=tuple(owners))

    def render(self) -> str:
        lines = ["# AGENTS.md", "", "## Module map"]
        lines += [f"- `{m}` — " for m in self.modules]
        lines += ["", "## Public API"]
        lines += [f"- `{s}`" for s in self.public_api]
        lines += ["", "## Ownership"]
        lines += [f"- `{p}` -> {o}" for p, o in self.ownership]
        return "\n".join(lines) + "\n"


def _split_sections(text: str) -> dict[str, list[str]]:
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
    m = _BACKTICK.search(line)
    return m.group(1) if m is not None else None


# `ownership` is stored as a tuple of pairs (hashable); expose dict where convenient.
def _eq_dict(doc: AgentsMd) -> dict[str, str]:
    return doc.ownership_map
```

Note the test compares `doc.ownership` to a dict — adjust the dataclass to expose `ownership` as a dict for ergonomics while staying frozen:

```python
# replace the field + property with a frozen dict view
from types import MappingProxyType

@dataclass(frozen=True)
class AgentsMd:
    modules: tuple[str, ...] = ()
    public_api: tuple[str, ...] = ()
    ownership: dict[str, str] | None = None  # path -> owner

    def __post_init__(self) -> None:
        object.__setattr__(self, "ownership", dict(self.ownership or {}))
```

(Keep whichever shape makes the Step-1 test pass; the test asserts `doc.ownership == {"...": "ada", ...}`, so the dict form is required. Drop `_eq_dict`/`ownership_map` if using the dict field.)

```python
# src/chorus/coherence/__init__.py
"""Cross-child coherence — the AGENTS.md contract + the deterministic reconciliation checker (spec 15)."""
from __future__ import annotations

from chorus.coherence._agents_md import AgentsMd

__all__ = ["AgentsMd"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/coherence/test_agents_md.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src/chorus/coherence tests/coherence && uv run mypy --strict src/chorus/coherence
git add src/chorus/coherence/__init__.py src/chorus/coherence/_agents_md.py tests/coherence/test_agents_md.py
git commit -m "feat(coherence): AGENTS.md codec — the cross-child contract (spec 15 §4.1)"
```

---

## Task 2: the deterministic coherence checker

**Files:**
- Create: `src/chorus/coherence/_checker.py`
- Modify: `src/chorus/coherence/__init__.py` (export `check_coherence`, `CoherenceViolation`)
- Test: `tests/coherence/test_checker.py`

Checks (spec §4.3), each a pure function over `(root: Path, doc: AgentsMd) -> list[CoherenceViolation]`:
1. `missing_module` — a declared module path doesn't exist on disk.
2. `duplicate_symbol` — a public symbol (last dotted component) is defined as a top-level `def`/`class` in **more than one** module file.
3. `missing_export` — a declared public symbol isn't bound in the package `__init__.py` (import or assignment or `__all__`).
4. `orphan_module` — a declared non-`__init__` module is imported by **no** other file in the package.
5. (importability is Task-3's CLI subprocess check, not a static check.)

- [ ] **Step 1: Write the failing test**

```python
# tests/coherence/test_checker.py
"""Deterministic coherence checks reconciled to AGENTS.md (spec 15 §4.3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from chorus.coherence import AgentsMd, check_coherence

pytestmark = pytest.mark.unit


def _pkg(tmp: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    root = _pkg(tmp_path, {
        "pkg/__init__.py": "from pkg.core import Thing\n__all__ = ['Thing']\n",
        "pkg/core.py": "class Thing:\n    pass\n",
    })
    doc = AgentsMd(modules=("pkg/__init__.py", "pkg/core.py"), public_api=("pkg.Thing",),
                   ownership={"pkg/core.py": "ada"})
    assert check_coherence(root, doc) == []


def test_missing_declared_module(tmp_path: Path) -> None:
    root = _pkg(tmp_path, {"pkg/__init__.py": "\n"})
    doc = AgentsMd(modules=("pkg/__init__.py", "pkg/core.py"))
    codes = [v.code for v in check_coherence(root, doc)]
    assert "missing_module" in codes


def test_duplicate_public_symbol(tmp_path: Path) -> None:
    root = _pkg(tmp_path, {
        "pkg/__init__.py": "from pkg.a import Trainer\n",
        "pkg/a.py": "class Trainer:\n    pass\n",
        "pkg/b.py": "class Trainer:\n    pass\n",  # rival definition
    })
    doc = AgentsMd(modules=("pkg/__init__.py", "pkg/a.py", "pkg/b.py"), public_api=("pkg.Trainer",))
    codes = [v.code for v in check_coherence(root, doc)]
    assert "duplicate_symbol" in codes


def test_init_missing_a_declared_export(tmp_path: Path) -> None:
    root = _pkg(tmp_path, {
        "pkg/__init__.py": "\n",  # exports nothing
        "pkg/core.py": "class Thing:\n    pass\n",
    })
    doc = AgentsMd(modules=("pkg/__init__.py", "pkg/core.py"), public_api=("pkg.Thing",))
    codes = [v.code for v in check_coherence(root, doc)]
    assert "missing_export" in codes


def test_orphan_module(tmp_path: Path) -> None:
    root = _pkg(tmp_path, {
        "pkg/__init__.py": "from pkg.core import Thing\n",
        "pkg/core.py": "class Thing:\n    pass\n",
        "pkg/dead.py": "X = 1\n",  # imported by nobody
    })
    doc = AgentsMd(modules=("pkg/__init__.py", "pkg/core.py", "pkg/dead.py"), public_api=("pkg.Thing",))
    codes = [v.code for v in check_coherence(root, doc)]
    assert "orphan_module" in codes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/coherence/test_checker.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_coherence'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/chorus/coherence/_checker.py
"""Deterministic coherence checks reconciled to AGENTS.md (spec 15 §4.3). Pure: filesystem + ast only."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from chorus.coherence._agents_md import AgentsMd


@dataclass(frozen=True)
class CoherenceViolation:
    code: str
    message: str
    path: str | None = None


def check_coherence(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    out: list[CoherenceViolation] = []
    out += _missing_modules(root, doc)
    out += _duplicate_symbols(root, doc)
    out += _missing_exports(root, doc)
    out += _orphan_modules(root, doc)
    return out


def _missing_modules(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    return [
        CoherenceViolation("missing_module", f"declared module is absent: {m}", m)
        for m in doc.modules
        if not (root / m).is_file()
    ]


def _top_level_defs(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _duplicate_symbols(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    wanted = {s.rsplit(".", 1)[-1] for s in doc.public_api}
    definers: dict[str, list[str]] = {}
    for m in doc.modules:
        p = root / m
        if not p.is_file() or p.name == "__init__.py":
            continue
        for name in _top_level_defs(p) & wanted:
            definers.setdefault(name, []).append(m)
    return [
        CoherenceViolation("duplicate_symbol", f"public symbol {name!r} defined in {mods}", None)
        for name, mods in definers.items()
        if len(mods) > 1
    ]


def _init_bound_names(root: Path, doc: AgentsMd) -> set[str]:
    init = next((root / m for m in doc.modules if m.endswith("__init__.py")), None)
    if init is None or not init.is_file():
        return set()
    try:
        tree = ast.parse(init.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
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


def _module_dotted(root: Path, m: str) -> str:
    return m[:-3].replace("/", ".") if m.endswith(".py") else m.replace("/", ".")


def _orphan_modules(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    # Build the set of imported dotted modules across the whole package.
    imported: set[str] = set()
    for m in doc.modules:
        p = root / m
        if not p.is_file():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
    out: list[CoherenceViolation] = []
    for m in doc.modules:
        if m.endswith("__init__.py"):
            continue
        dotted = _module_dotted(root, m)
        # imported if its full dotted path OR its parent package is referenced by a from-import
        if dotted not in imported and not any(i == dotted or i.endswith(dotted.rsplit(".", 1)[-1]) for i in imported):
            out.append(CoherenceViolation("orphan_module", f"module imported by nothing: {m}", m))
    return out
```

Update the package exports:

```python
# src/chorus/coherence/__init__.py
from chorus.coherence._agents_md import AgentsMd
from chorus.coherence._checker import CoherenceViolation, check_coherence

__all__ = ["AgentsMd", "CoherenceViolation", "check_coherence"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/coherence/test_checker.py -q`
Expected: PASS (5 passed). If `test_orphan_module` is flaky on the `endswith` heuristic, tighten `_orphan_modules` to compare on the final module component only (`dotted.rsplit('.',1)[-1] in {i.rsplit('.',1)[-1] for i in imported}`).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src/chorus/coherence tests/coherence && uv run mypy --strict src/chorus/coherence
git add -A src/chorus/coherence tests/coherence/test_checker.py
git commit -m "feat(coherence): deterministic checker — dup/missing-export/orphan/missing-module (spec 15 §4.3)"
```

---

## Task 3: the `python -m chorus.coherence` CLI (the gate command)

**Files:**
- Create: `src/chorus/coherence/__main__.py`
- Test: `tests/coherence/test_cli.py`

The CLI is what the manager's `Verifier.command` runs in the integrated worktree. It loads `AGENTS.md` from the root, runs `check_coherence`, then also does the **importability** check (`python -c "import <pkg>"` for each declared top-level package). Exits 1 with printed violations if any; 0 if clean. A missing `AGENTS.md` is itself a violation (`agents_md_missing`).

- [ ] **Step 1: Write the failing test**

```python
# tests/coherence/test_cli.py
"""`python -m chorus.coherence` — the integrate-gate command (spec 15 §4.3)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "chorus.coherence", "--root", str(root)],
        capture_output=True, text=True,
    )


def test_clean_tree_exits_zero(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from pkg.core import Thing\n__all__=['Thing']\n")
    (tmp_path / "pkg" / "core.py").write_text("class Thing:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n- `pkg/core.py` — Thing\n"
        "## Public API\n- `pkg.Thing`\n## Ownership\n- `pkg/core.py` -> ada\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_agents_md_fails(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "agents_md_missing" in (r.stdout + r.stderr)


def test_split_brain_duplicate_fails(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from pkg.a import Trainer\n")
    (tmp_path / "pkg" / "a.py").write_text("class Trainer:\n    pass\n")
    (tmp_path / "pkg" / "b.py").write_text("class Trainer:\n    pass\n")
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — e\n- `pkg/a.py` — a\n- `pkg/b.py` — b\n"
        "## Public API\n- `pkg.Trainer`\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "duplicate_symbol" in (r.stdout + r.stderr)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/coherence/test_cli.py -q`
Expected: FAIL — `No module named chorus.coherence.__main__`

- [ ] **Step 3: Write minimal implementation**

```python
# src/chorus/coherence/__main__.py
"""Run the coherence checker against a worktree; exit non-zero on any violation (spec 15 §4.3).

This is the command a manager's integrate DoD runs (Verifier.command("python -m chorus.coherence")):
it reconciles the merged tree on company main to AGENTS.md and is the structural rollup gate.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from chorus.coherence._agents_md import AgentsMd
from chorus.coherence._checker import CoherenceViolation, check_coherence


def _importable(root: Path, doc: AgentsMd) -> list[CoherenceViolation]:
    pkgs = sorted({m.split("/", 1)[0] for m in doc.modules if "/" in m})
    out: list[CoherenceViolation] = []
    for pkg in pkgs:
        r = subprocess.run(
            [sys.executable, "-c", f"import {pkg}"], cwd=str(root), capture_output=True, text=True
        )
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
            out.append(CoherenceViolation("not_importable", f"import {pkg} failed: {tail[0]}", pkg))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="chorus.coherence")
    ap.add_argument("--root", default=".", help="worktree root (company main)")
    ap.add_argument("--agents", default="AGENTS.md", help="contract file, relative to root")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    contract = root / args.agents
    if not contract.is_file():
        print(f"[coherence] FAILED: agents_md_missing — no {args.agents} at the deliverable root", flush=True)
        return 1
    doc = AgentsMd.parse(contract.read_text(encoding="utf-8"))
    violations = check_coherence(root, doc) + _importable(root, doc)
    if not violations:
        print("[coherence] OK: the merged tree is a single coherent surface", flush=True)
        return 0
    print(f"[coherence] FAILED: {len(violations)} violation(s):", flush=True)
    for v in violations:
        loc = f" ({v.path})" if v.path else ""
        print(f"  - {v.code}: {v.message}{loc}", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/coherence/test_cli.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check src/chorus/coherence && uv run mypy --strict src/chorus/coherence
git add src/chorus/coherence/__main__.py tests/coherence/test_cli.py
git commit -m "feat(coherence): python -m chorus.coherence gate command (spec 15 §4.3)"
```

---

## Task 4: gate the manager's integrate on coherence + record the verdict

The kernel already runs a manager's `Command` DoD at integrate (`_integrate_floor_verdict`). So "gate the integrate" = ensure the goal/manager task carries `Verifier.command("python -m chorus.coherence")`. In the standup harness that is `_pin_objective_dod`; in library use it is the goal's submitted DoD. We also record the coherence verdict on the subtree artifact for the audit trail.

**Files:**
- Modify: `standup-app/run.py` — add `_objective_goal_dod` returning `Verifier.command("python -m chorus.coherence")`, and pin it on the goal at submit (the `--org` goal) so `_integrate_floor_verdict` runs it.
- Modify: `src/chorus_employee/manager/_lander.py` — add `coherence` to the subtree `resource_ref` (run the checker against the worktree if available; best-effort, audit only).
- Test: `tests/employee/test_manager_lander.py` (extend) + a scheduler integrate test asserting a red coherence floor parks the goal `blocked`.

- [ ] **Step 1: Write the failing test (scheduler integrate floor on coherence)**

```python
# tests/heartbeat/test_coherence_gate.py
"""The manager integrate parks blocked when the coherence floor is red (spec 15 §4.3)."""
from __future__ import annotations

import pytest

from chorus.outcomes import Verifier

pytestmark = pytest.mark.unit


def test_coherence_dod_is_a_command_verifier() -> None:
    v = Verifier.command("python -m chorus.coherence", artifact_class="subtree")
    steps = v.verification_steps()
    assert len(steps) == 1
    assert steps[0].command == "python -m chorus.coherence"
```

(This locks the DoD shape; the full red-floor→blocked path is covered by extending the existing adaptive-loop tests in `tests/heartbeat/test_m3_park_integrate.py` — reuse `_integrate_floor_verdict` returning `False` and assert `blocked`. Mirror `test_integrate_lands_done_when_the_objective_rollup_floor_passes` but with a failing command.)

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `uv run pytest tests/heartbeat/test_coherence_gate.py -q`
Expected: PASS (the Verifier already supports this) — this is a guard test that locks the contract. If it errors, fix the import.

- [ ] **Step 3: Wire the goal DoD in the harness**

```python
# standup-app/run.py — add near _objective_engineer_dod
def _objective_goal_dod(intent: str) -> Verifier:
    """The director/goal rollup DoD = the coherence gate run against company main at integrate.

    The kernel's _integrate_floor_verdict runs this command in the integrator's worktree once the
    subtree is terminal; a red result parks the goal `blocked` with the coherence violations, and the
    adaptive integrate loop re-dispatches the manager to reconcile — never a silent split-brain done.
    """
    del intent
    return Verifier.command("python -m chorus.coherence", artifact_class="subtree")
```

Then in `_run_org`, submit the goal with `dod=_objective_goal_dod(goal_text)` (replacing the `rollup=None`), and ensure `AGENTS.md` + a coherence entrypoint are runnable in the worktree (chorus is installed in the venv, so `python -m chorus.coherence` resolves).

- [ ] **Step 4: Record the verdict in ManagerLander**

```python
# src/chorus_employee/manager/_lander.py — inside land(), before building the Artifact
from pathlib import Path  # add at top

# best-effort coherence note for the audit trail (the gate itself is the kernel floor)
coherence = "unknown"
# (left "unknown" here; the kernel floor is authoritative. Populate from the run outcome if surfaced.)
```

(Keep this minimal — the authoritative gate is `_integrate_floor_verdict`; the lander only annotates. Add `"coherence": coherence` to `resource_ref`.)

- [ ] **Step 5: Run the affected suites + commit**

Run: `uv run pytest tests/heartbeat tests/employee -q`
Expected: PASS (no regressions; the new guard test passes)

```bash
uv run ruff check standup-app/run.py src/chorus_employee/manager/_lander.py
git add standup-app/run.py src/chorus_employee/manager/_lander.py tests/heartbeat/test_coherence_gate.py
git commit -m "feat(coherence): pin the goal's integrate DoD to the coherence gate (spec 15 §4.3)"
```

---

## Task 5: the manager authors AGENTS.md at decompose

**Files:**
- Modify: `src/chorus_employee/manager/_brief.py` — instruct the manager to write `repo/AGENTS.md` (module map · public API · ownership) as the FIRST action of its kickoff decompose, and to re-write it (never append) on re-decompose.
- Modify: `src/chorus/lifecycle/_decompose.py` — seed an `AGENTS.md` skeleton deterministically at decompose time if absent, so the contract file always exists for the gate even before the manager fills it (the gate then reports `agents_md` incomplete rather than missing).
- Test: `tests/lifecycle/test_decompose_agents_md.py` — decompose writes a non-empty `AGENTS.md` skeleton into the manager's worktree.

- [ ] **Step 1: Write the failing test**

```python
# tests/lifecycle/test_decompose_agents_md.py
"""Decompose seeds repo/AGENTS.md so the coherence contract always exists (spec 15 §4.1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from chorus.lifecycle._decompose import seed_agents_md

pytestmark = pytest.mark.unit


def test_seed_writes_a_skeleton_when_absent(tmp_path: Path) -> None:
    seed_agents_md(tmp_path, goal_intent="Build dpo_tune: a Trainer + dpo_loss")
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Module map" in text and "## Public API" in text and "## Ownership" in text


def test_seed_does_not_clobber_an_existing_contract(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# AGENTS.md\nhand-authored\n", encoding="utf-8")
    seed_agents_md(tmp_path, goal_intent="x")
    assert "hand-authored" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/lifecycle/test_decompose_agents_md.py -q`
Expected: FAIL — `ImportError: cannot import name 'seed_agents_md'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/chorus/lifecycle/_decompose.py — add this helper (import AgentsMd lazily to avoid cycles)
def seed_agents_md(worktree: Path, *, goal_intent: str) -> None:
    """Write a skeleton repo/AGENTS.md if none exists, so the coherence contract is always present.

    The manager fills the module map / public API / ownership during its kickoff beat (per its brief);
    this guarantees the gate finds a contract file to reconcile to rather than `agents_md_missing`.
    """
    contract = worktree / "AGENTS.md"
    if contract.is_file():
        return
    skeleton = (
        "# AGENTS.md\n\n"
        f"<!-- goal: {goal_intent.strip().splitlines()[0][:120]} -->\n\n"
        "## Module map\n- `<package>/__init__.py` — package entry; re-exports the public API\n\n"
        "## Public API\n- `<package>.<Symbol>`\n\n"
        "## Ownership\n- `<package>/<file>.py` -> <employee_id>\n"
    )
    contract.write_text(skeleton, encoding="utf-8")
```

Add `from pathlib import Path` to the imports if not present.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/lifecycle/test_decompose_agents_md.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Add the manager brief instruction + commit**

Append to `MANAGER_BRIEF` (in `_brief.py`) a kickoff bullet:

```
"- AUTHOR THE CONTRACT FIRST. On your kickoff decompose, write `repo/AGENTS.md` declaring the "
"deliverable's MODULE MAP (each file + its purpose), PUBLIC API (the exact symbols `__init__` must "
"export), and OWNERSHIP (which child task owns which file — one owner per file). This is the single "
"contract your team builds to. Re-WRITE it to current truth on re-decompose (never append). Your "
"integrate is gated on the merged tree matching it: no duplicate public symbols, `__init__` exports "
"exactly the declared API, no orphan modules, the package imports clean.\n"
```

```bash
uv run pytest tests/lifecycle -q && uv run ruff check src/chorus/lifecycle src/chorus_employee/manager
git add src/chorus/lifecycle/_decompose.py src/chorus_employee/manager/_brief.py tests/lifecycle/test_decompose_agents_md.py
git commit -m "feat(coherence): manager authors AGENTS.md at decompose; seed skeleton (spec 15 §4.1)"
```

---

## Task 6: dream — export the dormant orientation + guard surface

**Files (dream repo `/Users/divyansh/Harness/src/dream`):**
- Modify: `src/dream/__init__.py` — export `run_orientation`, `OrientationConfig`, `OrientationBrief`, `session_start_findings`, `Finding`, `has_blocking`, `DreamPaths`.
- Test: `tests/test_public_surface.py` (dream) — the symbols import from `dream`.

- [ ] **Step 1: Write the failing test**

```python
# (dream repo) tests/test_orientation_surface.py
def test_orientation_stack_is_on_the_public_surface() -> None:
    import dream
    assert hasattr(dream, "run_orientation")
    assert hasattr(dream, "session_start_findings")
    assert hasattr(dream, "DreamPaths")
    assert hasattr(dream, "has_blocking")
```

- [ ] **Step 2: Run it (fails — not exported)**

Run (in dream repo): `uv run pytest tests/test_orientation_surface.py -q`
Expected: FAIL — `AttributeError: module 'dream' has no attribute 'run_orientation'`

- [ ] **Step 3: Add the exports**

In `src/dream/__init__.py`, add the imports + `__all__` entries:

```python
from dream.config.paths import DreamPaths
from dream.engine._orientation import OrientationBrief, OrientationConfig, run_orientation
from dream.services.repo_validator import Finding, has_blocking
from dream.services.session_guard import session_start_findings
```

(Append the four/seven names to `__all__`.)

- [ ] **Step 4: Run it (passes) + dream gate**

Run: `uv run pytest tests/test_orientation_surface.py -q` → PASS
Run dream's gate (its ruff/mypy/pytest).

- [ ] **Step 5: Commit (in dream repo)**

```bash
git -C /Users/divyansh/Harness add src/dream/__init__.py tests/test_orientation_surface.py
git -C /Users/divyansh/Harness commit -m "feat(surface): export orientation + session-guard for chorus spec-15"
```

---

## Task 7: dream — wire OrientationConfig through build_harness

**Files (dream):**
- Modify: `src/dream/_factory.py` — `build_harness(..., orientation: bool = False)`; when `True`, construct an `OrientationConfig` whose `gather` reads `AGENTS.md` (`DreamPaths.resolve(working_dir).agents_md`) + `session_start_findings(paths)` into an `OrientationBrief`, and thread it into the `SessionConfig` built in `make_session_config` / `_build_session_engine`.
- Test: `tests/test_orientation_wiring.py` (dream) — a harness built with `orientation=True` produces a `SessionConfig.orientation is not None`; the gathered brief contains the `AGENTS.md` text; a blocking finding (missing AGENTS.md) makes `has_blocking_findings` true.

- [ ] **Step 1: Write the failing test**

```python
# (dream repo) tests/test_orientation_wiring.py
import asyncio
from pathlib import Path

def test_gather_reads_agents_md(tmp_path: Path) -> None:
    from dream._factory import _build_orientation_config  # new helper
    (tmp_path / "AGENTS.md").write_text("# AGENTS.md\nhello-contract\n")
    cfg = _build_orientation_config(tmp_path)
    brief = asyncio.run(cfg.gather())
    assert "hello-contract" in brief.repo_summary
```

- [ ] **Step 2: Run it (fails — no helper)**

Expected: FAIL — `ImportError: cannot import name '_build_orientation_config'`

- [ ] **Step 3: Implement the helper + thread it**

```python
# src/dream/_factory.py
from dream.config.paths import DreamPaths
from dream.engine._orientation import OrientationBrief, OrientationConfig
from dream.services.session_guard import session_start_findings


def _build_orientation_config(working_dir: Path) -> OrientationConfig:
    paths = DreamPaths.resolve(working_dir)

    async def gather() -> OrientationBrief:
        agents = paths.agents_md.read_text(encoding="utf-8") if paths.agents_md.is_file() else ""
        findings = session_start_findings(paths)
        return OrientationBrief(
            repo_summary=agents,
            progress_tail="",
            active_exec_plan="",
            validator_findings=tuple(_to_validator_finding(f) for f in findings),
        )

    return OrientationConfig(gather=gather)
```

(Map `Finding` → the `ValidatorFinding` shape `run_orientation` expects; add `_to_validator_finding`. Then in `build_harness`, when `orientation=True`, pass `orientation=_build_orientation_config(working_dir)` into the `SessionConfig` construction in `_build_session_engine`/`make_session_config`.)

- [ ] **Step 4: Run it (passes) + dream gate**

- [ ] **Step 5: Commit (dream repo)** — `feat(orientation): wire AGENTS.md orientation into build_harness (spec 15 §4.2)`

---

## Task 8: chorus — turn orientation on for engineer beats

**Files:**
- Modify: `src/chorus_harness/_factory.py:389-403` — pass `orientation=True` into `dream.build_harness(...)` for write-capable (engineer/pm/tester) roles, so each beat reads `AGENTS.md` before writing.
- Test: extend `tests/harness/test_factory.py` — the engineer materialization passes `orientation=True` to the stubbed `build_harness` (assert via the captured kwargs, matching the existing stub pattern that captures `build_harness(**kw)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/harness/test_factory.py — add
def test_engineer_harness_enables_orientation(monkeypatch, tmp_path) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id="ada", name="Ada", role="engineer"))
    assert captured["orientation"] is True
```

- [ ] **Step 2: Run it (fails — KeyError 'orientation')**

- [ ] **Step 3: Pass orientation in the factory**

```python
# src/chorus_harness/_factory.py — in the build_harness(...) call
harness = dream.build_harness(
    ...,
    orientation=True,  # spec 15 §4.2 — read AGENTS.md before writing
)
```

- [ ] **Step 4: Run it (passes) + chorus gate** — `uv run pytest tests/harness -q`

- [ ] **Step 5: Commit** — `feat(coherence): engineer beats orient on AGENTS.md (spec 15 §4.2)`

---

## Task 9: keyed e2e — dpo_tune is single-surface or honestly blocked

**Files:**
- Test/script: reuse `standup-app/run.py --org` (or a small flat runner) keyed from `.env`.

- [ ] **Step 1:** Run `dpo_tune` through `--org` with the coherence goal-DoD on. Capture the run home.
- [ ] **Step 2:** Assert the landed company main is single-surface — `python -m chorus.coherence --root <main>` exits 0 — OR the goal ended `blocked` with coherence violations in the log. **Never** a `done` with `python -m chorus.coherence` red.
- [ ] **Step 3:** Record the verdict (contract present, declared modules present, `__init__` exports the API, imports clean) in the run report.

---

## Self-review

- **Spec coverage:** §4.1 contract = Tasks 1,5. §4.2 dream prevent-layer = Tasks 6,7,8. §4.3 coherence DoD + checks = Tasks 2,3,4. §4.3 reconciliation loop = reused kernel `_integrate_floor_verdict` + `max_integrate_iterations` (Task 4, no new code). §6 unit tests = Tasks 1-5; keyed e2e = Task 9. §8 success criterion = Task 9 assertion.
- **No new DoDKind:** confirmed — the coherence DoD is `Verifier.command`, and the integrate floor already runs `Command` DoDs (scheduler:640,719).
- **Type consistency:** `AgentsMd(modules, public_api, ownership)` and `CoherenceViolation(code, message, path)` are used identically across Tasks 1-4; `check_coherence(root, doc) -> list[CoherenceViolation]` signature stable.
- **Risk — orphan heuristic:** the `_orphan_modules` import match is heuristic; Task 2 Step 4 notes the tightening. **Risk — dream wiring depth:** Task 7 is the least-pinned (dream `SessionConfig` threading); do it behind the `orientation` flag so chorus default behavior is unchanged until proven.
- **Order:** Tasks 1→4 deliver the full chorus-side gate (the success criterion) independently; 6→8 add prevention; 9 validates. The chorus core can ship and be e2e-validated before the dream work.
