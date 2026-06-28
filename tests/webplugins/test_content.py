"""Content batch + swipe review — the fail-closed human accept/reject over drafts (spec GM §3)."""

from __future__ import annotations

import pytest

from chorus.webplugins import Draft, PluginKind, swipe_review

pytestmark = pytest.mark.unit


def _drafts() -> tuple[Draft, ...]:
    return (
        Draft(id="d1", channel=PluginKind.SOCIAL, body="post one"),
        Draft(id="d2", channel=PluginKind.SOCIAL, body="post two"),
        Draft(id="d3", channel=PluginKind.EMAIL_CRM, body="email three"),
    )


def test_accepted_subset_is_returned_in_presented_order() -> None:
    outcome = swipe_review(_drafts(), accept={"d3", "d1"})
    assert [d.id for d in outcome.accepted] == ["d1", "d3"]  # input order, not accept order
    assert [d.id for d in outcome.rejected] == ["d2"]
    assert outcome.any_accepted is True


def test_empty_accept_publishes_nothing_fail_closed() -> None:
    outcome = swipe_review(_drafts(), accept=set())
    assert outcome.accepted == ()
    assert [d.id for d in outcome.rejected] == ["d1", "d2", "d3"]
    assert outcome.any_accepted is False


def test_a_stale_accept_id_that_matches_no_draft_is_ignored() -> None:
    outcome = swipe_review(_drafts(), accept={"d1", "ghost"})
    assert [d.id for d in outcome.accepted] == ["d1"]
    assert "ghost" not in {d.id for d in outcome.accepted}
