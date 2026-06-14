"""``chorus`` CLI entrypoint — a thin wrapper over the :class:`chorus.Chorus` facade.

Intake via the CLI is the only way work enters until well after M4 — there are no
inbound Slack/GitHub channels (those are Arceus, post-M4) (spec 10 §2).

    chorus submit "<intent>" [--assignee E] [--dod CMD] [--depends-on T,...]
    chorus tick                       # one pulse (cron/dev)
    chorus run                        # run_forever
    chorus employees [list|hire|terminate]
    chorus routines  [list|add|pause]
    chorus inspect   [status|task <id>|events|stuck]
    chorus export <path> | import <path>     # portable package (spec 09)
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``chorus`` argument parser (spec 10 §2 command surface)."""
    parser = argparse.ArgumentParser(prog="chorus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="create an intake task")
    p_submit.add_argument("intent")
    p_submit.add_argument("--assignee")
    p_submit.add_argument("--dod")
    p_submit.add_argument("--depends-on", default="")

    sub.add_parser("tick", help="run one kernel pulse")
    sub.add_parser("run", help="run_forever")

    p_emp = sub.add_parser("employees", help="manage the workforce")
    p_emp.add_argument("action", choices=("list", "hire", "terminate"))

    p_routines = sub.add_parser("routines", help="manage cron routines")
    p_routines.add_argument("action", choices=("list", "add", "pause"))

    p_inspect = sub.add_parser("inspect", help="read the org's state")
    p_inspect.add_argument("view", choices=("status", "task", "events", "stuck"))
    p_inspect.add_argument("id", nargs="?")

    for verb in ("export", "import"):
        p = sub.add_parser(verb, help=f"{verb} a portable company/team package")
        p.add_argument("path")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint; wires the facade and dispatches the subcommand (spec 10 §2)."""
    build_parser().parse_args(argv)
    raise NotImplementedError("spec 10 §2: wire Chorus.build() and dispatch the subcommand")


if __name__ == "__main__":
    raise SystemExit(main())
