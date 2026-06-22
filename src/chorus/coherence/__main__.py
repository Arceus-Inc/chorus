"""Run the coherence checker against a worktree; exit non-zero on any violation (spec 15 §4.3).

This is the command a manager's integrate DoD runs (``Verifier.command("python -m chorus.coherence")``):
it reconciles the merged tree on company main to ``AGENTS.md`` and is the structural rollup gate. A red
result parks the goal ``blocked`` with the precise violations (via the kernel's integrate floor), and
the adaptive integrate loop re-dispatches the manager to reconcile — never a silent split-brain done.

Placeholder-aware: if the contract is still the seeded skeleton, the declared checks are skipped (a
note is printed) and only the structural split-brain + importability checks run, so coherent code is
never blocked merely because the manager has not authored the contract yet.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from chorus.coherence._agents_md import AgentsMd
from chorus.coherence._checker import (
    CoherenceViolation,
    _discover_packages,
    check_coherence,
    is_placeholder,
)


def _importable(root: Path) -> list[CoherenceViolation]:
    """Every top-level package in the tree imports in a clean subprocess (spec 15 §4.3, check 4)."""
    out: list[CoherenceViolation] = []
    for package in _discover_packages(root):
        result = subprocess.run(
            [sys.executable, "-c", f"import {package}"], cwd=str(root), capture_output=True, text=True
        )
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
            out.append(CoherenceViolation("not_importable", f"import {package} failed: {tail[0]}", package))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="chorus.coherence")
    parser.add_argument("--root", default=".", help="worktree root to check (company main)")
    parser.add_argument("--agents", default="AGENTS.md", help="contract file, relative to root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = root / args.agents
    if not contract.is_file():
        print(
            f"[coherence] FAILED: agents_md_missing — no {args.agents} at the deliverable root",
            flush=True,
        )
        return 1

    doc = AgentsMd.parse(contract.read_text(encoding="utf-8"))
    if is_placeholder(doc):
        print(
            "[coherence] NOTE: AGENTS.md is unauthored (still the placeholder) — running structural "
            "checks only (no-public-rival + imports-clean); the manager should author the real contract.",
            flush=True,
        )
    violations = check_coherence(root, doc) + _importable(root)
    if not violations:
        print("[coherence] OK: the merged tree is a single coherent surface", flush=True)
        return 0
    print(f"[coherence] FAILED: {len(violations)} violation(s):", flush=True)
    for violation in violations:
        location = f" ({violation.path})" if violation.path else ""
        print(f"  - {violation.code}: {violation.message}{location}", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
