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
    assert org._scheduler._landers is None  # unset → a passed beat lands without recording an artifact
