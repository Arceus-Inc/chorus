"""Task lifecycle rules (spec 02) — the status machine, liveness, and recovery glue.

Internal package: the rules the ledger/scheduler enforce on a task as it moves
through its lifecycle. Nothing here is part of chorus's public API (``chorus``);
the facade and repos consume it.
"""

from __future__ import annotations

from chorus.lifecycle._decompose import ChildSpec, decompose
from chorus.lifecycle._disposition import (
    Disposition,
    DispositionAction,
    reconcile_disposition,
)
from chorus.lifecycle._liveness import Health, Liveness, classify
from chorus.lifecycle._transitions import (
    LEGAL_TRANSITIONS,
    TERMINAL,
    IllegalTransition,
    assert_legal,
    entry_stamp,
    is_legal,
)

__all__ = [
    "LEGAL_TRANSITIONS",
    "TERMINAL",
    "ChildSpec",
    "Disposition",
    "DispositionAction",
    "Health",
    "IllegalTransition",
    "Liveness",
    "assert_legal",
    "classify",
    "decompose",
    "entry_stamp",
    "is_legal",
    "reconcile_disposition",
]
