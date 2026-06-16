"""``chorus`` CLI entrypoint — an interactive console over the durable ledger (spec 10 §2).

Today the console drives the parts of chorus that run end-to-end without a provider: seed the
workforce, submit and assign tasks, pass messages, and inspect the ledger. Running beats (the
scheduler's ``dream.run_task`` loop) needs a configured dream beat runner and stays out of this
console for now — see ``examples/real_beat.py``.

    chorus                 # open ./chorus.db and start the console
    chorus --db PATH       # open a specific ledger (':memory:' for a throwaway one)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from chorus.ledger import SqliteLedger
from chorus_cli._commands import REGISTRY
from chorus_cli._context import CliSession
from chorus_cli._repl import run_repl

_DEFAULT_DB = "chorus.db"


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``chorus`` argument parser."""
    parser = argparse.ArgumentParser(prog="chorus", description=__doc__)
    parser.add_argument(
        "--db",
        default=_DEFAULT_DB,
        help=f"ledger database path (default: {_DEFAULT_DB!r}; ':memory:' for a throwaway one)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    input_func: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> int:
    """Parse args, open the ledger, and run the interactive console until quit (spec 10 §2).

    ``input_func`` / ``output`` are injectable so the whole entrypoint can be driven from a test with
    scripted input and a captured stream; they default to real stdin/stdout.
    """
    args = build_parser().parse_args(argv)
    ledger = SqliteLedger.open(args.db)
    try:
        return run_repl(
            CliSession(ledger=ledger),
            REGISTRY,
            input_func=input_func,
            output=output if output is not None else sys.stdout,
        )
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
