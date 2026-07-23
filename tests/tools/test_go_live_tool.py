"""GoLiveTool — the marketer's ``stage_go_live`` capability as a model-callable dream tool (§07/§11).

The high-risk operation (publish/send/spend) is an explicit typed micro-tool whose *call* opens a
human approval gate and returns the harness observation contract (status/summary/next_actions/
artifacts). It NEVER executes the effect — fail-closed. The tool is a thin dream envelope that
composes governance's public :meth:`~chorus.governance.GovernanceResolver.open_task_gate`; nothing new
is added to core chorus. These tests drive ``execute`` directly (no model, no keys).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.testing import open_test_ledger, uid
from chorus_tools import GoLiveTool

pytestmark = pytest.mark.integration


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


@pytest.fixture
def ledger() -> Ledger:
    lg = open_test_ledger()
    lg.tasks.submit(Task(id=uid("t1"), intent="launch", status=TaskStatus.IN_PROGRESS))
    return lg


def _run(ledger: Ledger, tmp_path: Path, payload: Mapping[str, object]) -> object:
    BeatContext(task_id=uid("t1"), run_id=uid("r1"), employee_id="mira").write(tmp_path)
    return asyncio.run(GoLiveTool(ledger).execute(dict(payload), _ctx(tmp_path)))


class TestStaging:
    def test_valid_publish_opens_a_gate(self, ledger: Ledger, tmp_path: Path) -> None:
        result = _run(
            ledger,
            tmp_path,
            {"action": "publish", "target": "blog", "content_ref": "content_draft.md"},
        )
        assert result.is_error is False  # type: ignore[attr-defined]
        assert "status: gated" in result.content  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 1

    def test_spend_with_amount_is_gated(self, ledger: Ledger, tmp_path: Path) -> None:
        result = _run(
            ledger,
            tmp_path,
            {
                "action": "spend",
                "target": "meta",
                "content_ref": "creative_set.md",
                "amount_cents": 50000,
            },
        )
        assert result.is_error is False  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 1

    def test_never_executes_the_effect(self, ledger: Ledger, tmp_path: Path) -> None:
        # Fail-closed: the tool stages + gates. The go-live never runs — the task is parked BLOCKED
        # (gated on human authorization), NOT marked done, and the gate stays pending.
        _run(ledger, tmp_path, {"action": "send", "target": "list", "content_ref": "sequence.md"})
        task = ledger.tasks.get(uid("t1"))
        assert task is not None and task.status is TaskStatus.BLOCKED  # gated, not executed
        assert task.status is not TaskStatus.DONE
        assert ledger.approvals.pending()[0].status.value == "pending"


class TestObservationContract:
    def test_result_carries_next_actions_and_artifacts(
        self, ledger: Ledger, tmp_path: Path
    ) -> None:
        result = _run(
            ledger,
            tmp_path,
            {"action": "publish", "target": "blog", "content_ref": "content_draft.md"},
        )
        gate_id = ledger.approvals.pending()[0].id
        assert "next_actions" in result.content  # type: ignore[attr-defined]
        assert gate_id in result.content  # type: ignore[attr-defined]
        assert result.metadata["status"] == "gated"  # type: ignore[attr-defined]
        assert result.metadata["gate_id"] == gate_id  # type: ignore[attr-defined]


class TestIdempotency:
    def test_second_call_returns_the_standing_gate(self, ledger: Ledger, tmp_path: Path) -> None:
        payload = {"action": "publish", "target": "blog", "content_ref": "content_draft.md"}
        first = _run(ledger, tmp_path, payload)
        second = _run(ledger, tmp_path, payload)
        assert first.metadata["gate_id"] == second.metadata["gate_id"]  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 1  # one beat, one gate


class TestErrorRecoveryContract:
    def test_spend_without_amount_errors_with_a_recovery_hint(
        self, ledger: Ledger, tmp_path: Path
    ) -> None:
        result = _run(ledger, tmp_path, {"action": "spend", "target": "meta", "content_ref": "c"})
        assert result.is_error is True  # type: ignore[attr-defined]
        assert "safe_retry" in result.content  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 0  # nothing staged on a bad request

    def test_non_spend_with_amount_errors(self, ledger: Ledger, tmp_path: Path) -> None:
        result = _run(
            ledger,
            tmp_path,
            {"action": "publish", "target": "blog", "content_ref": "c", "amount_cents": 500},
        )
        assert result.is_error is True  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 0

    def test_unknown_action_errors_without_staging(self, ledger: Ledger, tmp_path: Path) -> None:
        result = _run(
            ledger, tmp_path, {"action": "delete_everything", "target": "x", "content_ref": "c"}
        )
        assert result.is_error is True  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 0


class TestRestageGuard:
    """An approved-but-undelivered gate must be EXECUTED, not re-staged (the duplicate-gate bug)."""

    def _approve_first_gate(self, ledger: Ledger) -> str:
        gate = ledger.approvals.pending()[0]
        ledger.approvals.approve(gate.id, decided_by_user_id=uid("board"))
        return gate.id

    def test_restage_rejected_while_approved_gate_awaits_execution(
        self, ledger: Ledger, tmp_path: Path
    ) -> None:
        payload = {"action": "publish", "target": "blog", "content_ref": "content_draft.md"}
        _run(ledger, tmp_path, payload)
        gate_id = self._approve_first_gate(ledger)

        result = _run(ledger, tmp_path, payload)

        assert result.is_error is True  # type: ignore[attr-defined]
        assert "execute_go_live" in result.content  # type: ignore[attr-defined]
        assert gate_id in result.content  # type: ignore[attr-defined]
        assert ledger.approvals.pending() == []  # no duplicate gate opened

    def test_restage_allowed_after_the_delivery_landed(
        self, ledger: Ledger, tmp_path: Path
    ) -> None:
        from chorus_tools._go_live import GoLiveAction
        from chorus_tools.delivery import DeliveryRecord, PublishedRef
        from chorus_tools.delivery._index import DeliveryIndex

        payload = {"action": "publish", "target": "blog", "content_ref": "content_draft.md"}
        _run(ledger, tmp_path, payload)
        gate_id = self._approve_first_gate(ledger)
        DeliveryIndex(tmp_path / ".harness" / "deliveries.json").record(
            DeliveryRecord(
                approval_id=gate_id,
                action=GoLiveAction.PUBLISH,
                target="blog",
                published=PublishedRef(backend="strapi", ref_id=uid("d1"), url="u://d1"),
            )
        )

        result = _run(ledger, tmp_path, payload)  # a genuinely NEW reach for the same task

        assert result.is_error is False  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 1
