"""``Chorus.build`` exposes the landing seam (spec 14 F7).

A beat dispatched through the public front door must be able to *land* its deliverable — the engineer's
PR snapshot, the manager's subtree merge. The kernel stays dream-free and employee-free, so the
consumer injects landing the same way it injects execution: ``build(..., landers=factory.landers)``.
Without this seam the §0 example runs a real beat whose output goes nowhere — an incomplete front door.
"""

from __future__ import annotations

import pytest

from chorus.facade import Chorus
from chorus.outcomes import LanderRegistry

pytestmark = pytest.mark.integration


def _build(**over: object) -> Chorus:
    base: dict[str, object] = {
        "db_path": ":memory:",
        "org_repo": "/tmp/chorus-f7-org",
        "memory_repo": "/tmp/chorus-f7-mem",
        "dream": None,
    }
    base.update(over)
    return Chorus.build(**base)  # type: ignore[arg-type]


def test_build_threads_landers_into_the_scheduler() -> None:
    landers = LanderRegistry()
    org = _build(landers=landers)
    assert org._scheduler._landers is landers  # the injected seam reaches the dispatch path


def test_build_defaults_to_no_landers() -> None:
    org = _build()
    assert (
        org._scheduler._landers is None
    )  # unset → a passed beat lands without recording an artifact


def test_build_shares_an_injected_ledger() -> None:
    """``ledger=`` lets the consumer hand build the *same* store the harness factory holds — so a
    reviewed-build reviewer (a capability tool) records its verdict into one ledger, not two."""
    from chorus.ledger import SqliteLedger

    store = SqliteLedger.open(":memory:")
    try:
        org = Chorus.build(
            ledger=store,
            org_repo="/tmp/chorus-f7-org",
            memory_repo="/tmp/chorus-f7-mem",
            dream=None,
        )
        assert org._ledger is store  # the injected store is the one the kernel uses
    finally:
        store.close()


def test_build_rejects_both_db_path_and_ledger() -> None:
    from chorus.ledger import SqliteLedger

    store = SqliteLedger.open(":memory:")
    try:
        with pytest.raises(ValueError, match="db_path"):
            Chorus.build(
                db_path=":memory:",
                ledger=store,
                org_repo="/tmp/o",
                memory_repo="/tmp/m",
                dream=None,
            )
    finally:
        store.close()


def test_build_requires_db_path_or_ledger() -> None:
    with pytest.raises(ValueError, match="db_path"):
        Chorus.build(org_repo="/tmp/o", memory_repo="/tmp/m", dream=None)
