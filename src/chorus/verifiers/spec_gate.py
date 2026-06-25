"""Spec artifact Definition-of-Done gate.

Run from a task worktree with an optional plan filename. The gate passes only when the named file
exists and is non-empty.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    name = args[0] if args else "plan.md"
    plan = Path(name)
    if plan.is_file() and plan.stat().st_size > 0:
        print(f"[spec] OK: {name} is present and non-empty", flush=True)
        return 0
    print(f"[spec] FAILED: {name} is missing or empty", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())