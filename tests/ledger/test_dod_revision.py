"""dod revision persistence (§1 DoD revisability) — apply / propose / promote / clear.

A revision bumps ``dod.revision`` and swaps the in-force verifier; a *loosen* awaiting approval is
staged in ``dod.proposed_revision`` (the old verifier stays in force) until promoted. The recorded
verdict evidence is never disturbed by a revision (the in-flight invariant).
"""

from __future__ import annotations

import pytest

from chorus.ledger import DodStatus, Ledger, Task, TaskStatus
from chorus.outcomes import DoDKind, Verifier
from chorus.testing import uid

pytestmark = pytest.mark.integration


def test_apply_revision_bumps_revision_and_swaps_the_verifier(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship", status=TaskStatus.TODO))
    ledger.dod.create(uid("t1"), Verifier.command("pytest"))
    ledger.dod.apply_revision(uid("t1"), Verifier.command("pytest && ruff check"))

    dod = ledger.dod.get_for_task(uid("t1"))
    assert dod is not None and dod.revision == 2
    verifier = ledger.dod.verifier_for_task(uid("t1"))
    assert verifier is not None and verifier.kind is DoDKind.COMMAND
    assert verifier.verification_steps()[0].command == "pytest && ruff check"


def test_apply_revision_preserves_recorded_verdict(ledger: Ledger) -> None:
    # the in-flight invariant: a revision swaps the bar but never re-judges already-recorded evidence.
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship", status=TaskStatus.TODO))
    dod = ledger.dod.create(uid("t1"), Verifier.command("pytest"))
    ledger.dod.record_verdict(dod.id, DodStatus.PASSED, verdict={"ok": True})
    ledger.dod.apply_revision(uid("t1"), Verifier.command("pytest && ruff check"))

    after = ledger.dod.get_for_task(uid("t1"))
    assert after is not None
    assert after.verdict == {"ok": True}  # the recorded evidence is untouched by a revision
    assert after.status is DodStatus.PASSED


def test_propose_revision_stages_without_touching_the_in_force_verifier(
    ledger: Ledger,
) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship", status=TaskStatus.TODO))
    ledger.dod.create(uid("t1"), Verifier.agent_review(rubric="be strict"))
    ledger.dod.propose_revision(uid("t1"), Verifier.command("pytest"))  # a loosen, staged

    dod = ledger.dod.get_for_task(uid("t1"))
    assert dod is not None
    assert dod.revision == 1  # not bumped yet
    assert ledger.dod.verifier_for_task(uid("t1")).kind is DoDKind.AGENT_REVIEW  # type: ignore[union-attr]
    assert dod.proposed_revision is not None  # the staged loosen


def test_apply_proposed_revision_promotes_and_clears(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship", status=TaskStatus.TODO))
    ledger.dod.create(uid("t1"), Verifier.agent_review(rubric="be strict"))
    ledger.dod.propose_revision(uid("t1"), Verifier.command("pytest"))
    ledger.dod.apply_proposed_revision(uid("t1"))

    dod = ledger.dod.get_for_task(uid("t1"))
    assert dod is not None
    assert dod.revision == 2
    assert dod.proposed_revision is None  # cleared
    assert ledger.dod.verifier_for_task(uid("t1")).kind is DoDKind.COMMAND  # type: ignore[union-attr]


def test_clear_proposed_drops_the_staged_revision(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship", status=TaskStatus.TODO))
    ledger.dod.create(uid("t1"), Verifier.agent_review(rubric="be strict"))
    ledger.dod.propose_revision(uid("t1"), Verifier.command("pytest"))
    ledger.dod.clear_proposed(uid("t1"))

    dod = ledger.dod.get_for_task(uid("t1"))
    assert dod is not None and dod.proposed_revision is None
    assert ledger.dod.verifier_for_task(uid("t1")).kind is DoDKind.AGENT_REVIEW  # type: ignore[union-attr]
