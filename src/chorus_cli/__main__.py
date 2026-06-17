"""``chorus`` CLI entrypoint — an interactive console over the durable ledger (spec 10 §2).

Today the console drives the parts of chorus that run end-to-end without a provider: seed the
workforce, submit and assign tasks, pass messages, and inspect the ledger. Running beats (the
scheduler's ``dream.run_task`` loop) needs a configured dream beat runner and stays out of this
console for now — see ``examples/real_beat.py``.

    chorus                 # open ./chorus.db and start the console
    chorus --db PATH       # open a specific ledger (':memory:' for a throwaway one)

Set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_DEPLOYMENT to enable the ``tick`` and
``chat`` commands — ``tick`` is one kernel pulse that dispatches a real beat through dream; ``chat
<employee>`` is a conversational sub-loop where each line you type runs a beat and streams the
employee's reply back. Without them the console runs keys-free (everything but ``tick`` / ``chat``).
Beats are priced with CHORUS_PRICE_INPUT_CENTS_PER_MTOK / CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK
(illustrative defaults) so the budget gates have real spend to act on.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from chorus.ledger import SqliteLedger
from chorus_cli._commands import REGISTRY
from chorus_cli._context import BeatService, CliSession
from chorus_cli._env import load_env_file
from chorus_cli._repl import run_repl

_DEFAULT_DB = "chorus.db"
_DEFAULT_ENV = ".env"
_DEFAULT_COMPANY = "company"


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``chorus`` argument parser."""
    parser = argparse.ArgumentParser(prog="chorus", description=__doc__)
    parser.add_argument(
        "--db",
        default=_DEFAULT_DB,
        help=f"ledger database path (default: {_DEFAULT_DB!r}; ':memory:' for a throwaway one)",
    )
    parser.add_argument(
        "--env-file",
        default=_DEFAULT_ENV,
        help=f"dotenv file to load credentials from (default: {_DEFAULT_ENV!r})",
    )
    parser.add_argument(
        "--company",
        default=_DEFAULT_COMPANY,
        help=f"company id for company-wide budgets (default: {_DEFAULT_COMPANY!r})",
    )
    return parser


def _beat_service_from_env(ledger: SqliteLedger, *, company_id: str) -> BeatService | None:
    """Wire a real, priced, budget-enforcing beat service from Azure creds, or ``None`` if unset.

    dream is imported **lazily** here — only when all three credentials are present — so the keys-free
    console never imports the SDK. This is the CLI's composition seam for the kernel.
    """
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (api_key and base_url and deployment):
        return None
    from chorus_cli._beats import build_beat_service, default_pricing_from_env

    return build_beat_service(
        ledger,
        api_key=api_key,
        base_url=base_url,
        deployment=deployment,
        company_id=company_id,
        pricing=default_pricing_from_env(),
        seed=os.environ.get("CHORUS_COMPANY_SEED") or None,
    )


def _utf8_stdout() -> TextIO:
    """Return ``sys.stdout`` forced to UTF-8 so the console's glyphs (``-> -- cent``) never
    crash or mojibake on a Windows cp1252 terminal. A no-op where stdout is already UTF-8 or
    cannot be reconfigured (e.g. a redirected pipe that lacks ``reconfigure``).
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    return sys.stdout


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

    def _warn_env_override(key: str) -> None:
        # The .env is authoritative for its creds, but a stale shell export is worth flagging: it is
        # exactly the trap where a wrong AZURE_OPENAI_* silently breaks every beat (the model can't be
        # reached, so the planner sees an empty reply).
        print(
            f"warning: {key} was set in your shell; using {args.env_file} instead "
            f"(unset it or update {args.env_file} to silence this).",
            file=sys.stderr,
        )

    # ``override`` so the gitignored .env wins over a stale shell var; warn on each real conflict.
    load_env_file(Path(args.env_file), override=True, on_conflict=_warn_env_override)
    ledger = SqliteLedger.open(args.db)
    sink = output if output is not None else _utf8_stdout()
    try:
        beats = _beat_service_from_env(ledger, company_id=args.company)
        # ``input_func`` rides on the session too (not just ``run_repl``) so the modal ``chat``
        # sub-loop reads from the same source after a command hands off to it.
        session = CliSession(
            ledger=ledger, beats=beats, company_id=args.company, input_func=input_func
        )
        return run_repl(
            session,
            REGISTRY,
            input_func=input_func,
            output=sink,
        )
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
