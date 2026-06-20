"""``python -m experiments.insights <ledger.db> [section]`` — the insights CLI.

Sections: ``overview`` (default), ``ledger``, ``tree``, ``memory``, ``tools``, or ``all``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from experiments.insights import VIEWS, ExperimentSources
from experiments.insights import _render as r

_SECTIONS = (*VIEWS.keys(), "all")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.insights",
        description="Observability views over one experiment run's ledger, events, and memory.",
    )
    parser.add_argument("db", type=Path, help="path to the run's ledger.db")
    parser.add_argument(
        "section",
        nargs="?",
        default="overview",
        choices=_SECTIONS,
        help="which view to render (default: overview)",
    )
    parser.add_argument("--events", type=Path, default=None, help="override path to events.jsonl")
    parser.add_argument("--memory", type=Path, default=None, help="override path to the memory dir")
    parser.add_argument(
        "--root", type=Path, default=None, help="search root for auto-locating events/memory"
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.no_color:
        r.set_color(False)
    if not args.db.exists():
        print(f"error: no ledger at {args.db}", file=sys.stderr)
        return 2

    names = list(VIEWS) if args.section == "all" else [args.section]
    with ExperimentSources.discover(
        args.db, events_path=args.events, memory_dir=args.memory, search_root=args.root
    ) as sources:
        blocks = [VIEWS[name](sources) for name in names]
    print("\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
