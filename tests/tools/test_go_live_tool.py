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
from chorus.ledger import SqliteLedger, Task, TaskStatus
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
def ledger() -> SqliteLedger:
    lg = SqliteLedger.open(":memory:")
    lg.tasks.submit(Task(id="t1", intent="launch", status=TaskStatus.IN_PROGRESS))
    return lg


def _run(ledger: SqliteLedger, tmp_path: Path, payload: Mapping[str, object]) -> object:
    BeatContext(task_id="t1", run_id="r1", employee_id="mira").write(tmp_path)
    return asyncio.run(GoLiveTool(ledger).execute(dict(payload), _ctx(tmp_path)))


class TestStaging:
    def test_valid_publish_opens_a_gate(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        result = _run(ledger, tmp_path, {"action": "publish", "target": "blog", "content_ref": "content_draft.md"})
        assert result.is_error is False  # type: ignore[attr-defined]
        assert "status: gated" in result.content  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 1

    def test_spend_with_amount_is_gated(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        result = _run(
            ledger, tmp_path,
            {"action": "spend", "target": "meta", "content_ref": "creative_set.md", "amount_cents": 50000},
        )
        assert result.is_error is False  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 1

    def test_never_executes_the_effect(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        # Fail-closed: the tool stages + gates. The go-live never runs — the task is parked BLOCKED
        # (gated on human authorization), NOT marked done, and the gate stays pending.
        _run(ledger, tmp_path, {"action": "send", "target": "list", "content_ref": "sequence.md"})
        task = ledger.tasks.get("t1")
        assert task is not None and task.status is TaskStatus.BLOCKED  # gated, not executed
        assert task.status is not TaskStatus.DONE
        assert ledger.approvals.pending()[0].status.value == "pending"


class TestObservationContract:
    def test_result_carries_next_actions_and_artifacts(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        result = _run(ledger, tmp_path, {"action": "publish", "target": "blog", "content_ref": "content_draft.md"})
        gate_id = ledger.approvals.pending()[0].id
        assert "next_actions" in result.content  # type: ignore[attr-defined]
        assert gate_id in result.content  # type: ignore[attr-defined]
        assert result.metadata["status"] == "gated"  # type: ignore[attr-defined]
        assert result.metadata["gate_id"] == gate_id  # type: ignore[attr-defined]


class TestIdempotency:
    def test_second_call_returns_the_standing_gate(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        payload = {"action": "publish", "target": "blog", "content_ref": "content_draft.md"}
        first = _run(ledger, tmp_path, payload)
        second = _run(ledger, tmp_path, payload)
        assert first.metadata["gate_id"] == second.metadata["gate_id"]  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 1  # one beat, one gate


class TestErrorRecoveryContract:
    def test_spend_without_amount_errors_with_a_recovery_hint(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        result = _run(ledger, tmp_path, {"action": "spend", "target": "meta", "content_ref": "c"})
        assert result.is_error is True  # type: ignore[attr-defined]
        assert "safe_retry" in result.content  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 0  # nothing staged on a bad request

    def test_non_spend_with_amount_errors(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        result = _run(
            ledger, tmp_path,
            {"action": "publish", "target": "blog", "content_ref": "c", "amount_cents": 500},
        )
        assert result.is_error is True  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 0

    def test_unknown_action_errors_without_staging(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        result = _run(ledger, tmp_path, {"action": "delete_everything", "target": "x", "content_ref": "c"})
        assert result.is_error is True  # type: ignore[attr-defined]
        assert len(ledger.approvals.pending()) == 0
