"""DoD revision strictness classifier (§1 DoD revisability) — tighten vs loosen, fail-closed.

Each ``Verifier`` reduces to a set of obligations; a revision is a **tighten** only when the new set is
a strict superset of the old (you can only *add* obligations without sign-off). Everything else — a
dropped/swapped check, a different kind of gate, or anything not provably stricter — is a **loosen**.
"""

from __future__ import annotations

import pytest

from chorus.outcomes import Verifier
from chorus.outcomes._revision import RevisionDirection, classify

pytestmark = pytest.mark.unit


def test_adding_an_and_conjunct_is_a_tighten() -> None:
    old = Verifier.command("pytest")
    new = Verifier.command("pytest && ruff check")
    assert classify(old, new) is RevisionDirection.TIGHTEN


def test_dropping_a_conjunct_is_a_loosen() -> None:
    old = Verifier.command("pytest && ruff check")
    new = Verifier.command("pytest")
    assert classify(old, new) is RevisionDirection.LOOSEN


def test_swapping_a_command_is_a_loosen() -> None:
    # the engine can't prove the new text is stricter → fail closed to loosen.
    old = Verifier.command("pytest")
    new = Verifier.command("echo ok")
    assert classify(old, new) is RevisionDirection.LOOSEN


def test_identical_verifier_is_no_change() -> None:
    v = Verifier.command("pytest && ruff check")
    assert classify(v, v) is RevisionDirection.NO_CHANGE


def test_cross_kind_change_is_a_loosen() -> None:
    # command → human approval is a *different* gate, not a provable superset → loosen.
    old = Verifier.command("pytest")
    new = Verifier.human_approval()
    assert classify(old, new) is RevisionDirection.LOOSEN


def test_conjunct_order_does_not_matter() -> None:
    # obligations are a set — reordering is not a change.
    old = Verifier.command("pytest && ruff check")
    new = Verifier.command("ruff check && pytest")
    assert classify(old, new) is RevisionDirection.NO_CHANGE
