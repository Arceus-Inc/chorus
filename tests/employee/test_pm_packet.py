"""The decision packet — sources.json rendered from the ledger rows (§10, slice 5).

The packet is a deterministic read-model projection: every decision for the task with its cited
evidence, and every source with the decisions that rest on it. It reads claims via one batched query
(no N+1). The PmLander writes it into the worktree so a landed plan ships with an auditable trail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chorus.ledger import Ledger, Task, TaskStatus
from chorus.ledger._models import Claim, DecisionRecord
from chorus.testing import open_test_ledger, uid
from chorus.workspace import CompanyWorkspace
from chorus_employee.pm import pm_lander, render_packet

pytestmark = pytest.mark.integration


def _claim_id(decision_id: str, n: int) -> str:
    """A deterministic uuid claim id per (decision, index) — claim ids are uuid columns."""
    return uid(f"{decision_id}-c{n}")


def _seed_decision(
    ledger: Ledger, *, decision_id: str = uid("d1"), task_id: str = uid("t1")
) -> None:
    ledger.decisions.create(
        DecisionRecord(
            id=decision_id,
            task_id=task_id,
            option="build presence indicators",
            rationale="run opacity",
            confidence=0.82,
            outcome_metric="tickets down 30%",
            revisit_trigger="reopen if flat",
        )
    )
    ledger.claims.create(
        Claim(
            id=_claim_id(decision_id, 0),
            decision_id=decision_id,
            text="a",
            source_url="https://a",
            confidence=0.9,
        )
    )
    ledger.claims.create(
        Claim(
            id=_claim_id(decision_id, 1),
            decision_id=decision_id,
            text="b",
            source_url="https://b",
            confidence=0.7,
        )
    )


class TestRenderPacket:
    def test_projects_decisions_and_their_evidence(self, ledger: Ledger) -> None:
        _seed_decision(ledger)
        packet = render_packet(ledger, uid("t1"))

        assert packet["exportScope"] == "team"
        assert len(packet["decisions"]) == 1
        decision = packet["decisions"][0]
        assert decision["id"] == uid("d1")
        assert decision["option"] == "build presence indicators"
        assert decision["evidenceIds"] == sorted([_claim_id(uid("d1"), 0), _claim_id(uid("d1"), 1)])
        assert decision["supersededBy"] is None

    def test_sources_group_by_uri_with_citing_decisions(self, ledger: Ledger) -> None:
        _seed_decision(ledger)
        packet = render_packet(ledger, uid("t1"))
        uris = {s["uri"]: s for s in packet["sources"]}
        assert set(uris) == {"https://a", "https://b"}
        assert uris["https://a"]["citedInDecisions"] == [uid("d1")]

    def test_supersede_shows_forward_pointer(self, ledger: Ledger) -> None:
        _seed_decision(ledger, decision_id=uid("d1"))
        _seed_decision(ledger, decision_id=uid("d2"))
        ledger.decisions.set_superseded_by(uid("d1"), uid("d2"))
        packet = render_packet(ledger, uid("t1"))
        by_id = {d["id"]: d for d in packet["decisions"]}
        assert by_id[uid("d1")]["supersededBy"] == uid("d2")
        assert by_id[uid("d2")]["supersededBy"] is None

    def test_empty_task_renders_an_empty_but_valid_packet(self, ledger: Ledger) -> None:
        packet = render_packet(ledger, uid("nothing-here"))
        assert packet == {"decisions": [], "sources": [], "exportScope": "team"}


class TestLanderWritesThePacket:
    def test_lander_renders_sources_json_into_the_worktree(self, tmp_path: Path) -> None:
        company_root = tmp_path / "acme"
        ledger = open_test_ledger()
        try:
            _seed_decision(ledger, task_id=uid("t1"))
            workspace = CompanyWorkspace(company_root)
            worktree = workspace.worktree_for(uid("piper"))
            (worktree.path / "plan.md").write_text("# Plan\n", encoding="utf-8")

            task = Task(
                id=uid("t1"),
                intent="decide",
                status=TaskStatus.IN_PROGRESS,
                assignee_employee_id=uid("piper"),
            )
            import asyncio

            asyncio.run(pm_lander(company_root, ledger=ledger).land(task, None))

            packet = json.loads((worktree.path / "sources.json").read_text(encoding="utf-8"))
            assert packet["decisions"][0]["id"] == uid("d1")
            assert {s["uri"] for s in packet["sources"]} == {"https://a", "https://b"}
        finally:
            ledger.close()
