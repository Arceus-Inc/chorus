"""ExecuteGoLiveTool — the fail-closed go-live executor (design doc: the tool).

The full matrix: unapproved reach can NEVER execute (no beat context / no gate / pending / denied /
wrong-task approval id), an approved gate publishes exactly once (idempotent), and only the standing
staged draft is publishable. The backend is a fake — the real ones are tested apart.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import Approval, ApprovalGate, ApprovalSubjectKind, SqliteLedger
from chorus_tools.cms import ContentType, DraftRef
from chorus_tools.cms._index import CmsDraftIndex
from chorus_tools.delivery import DeliveryError, PublishedRef
from chorus_tools.delivery._index import DeliveryIndex
from chorus_tools.delivery._tool import ExecuteGoLiveInput, ExecuteGoLiveTool

pytestmark = pytest.mark.integration

_TASK = "task-1"


class _FakeBackend:
    def __init__(self) -> None:
        self.published: list[DraftRef] = []

    def publish(self, draft: DraftRef) -> PublishedRef:
        self.published.append(draft)
        return PublishedRef(backend="fake", ref_id=draft.ref_id, url=f"live://{draft.ref_id}")


class _RaisingBackend:
    def publish(self, draft: DraftRef) -> PublishedRef:
        raise DeliveryError("strapi publish 500: boom")


def _ctx(working_dir: Path) -> Any:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir, session_id="s", metadata={}, scratch_dir=working_dir,
        cancel_requested=False,
    )


def _wire_beat(tmp: Path, task_id: str = _TASK) -> None:
    BeatContext(task_id=task_id, run_id="r1", employee_id="mira").write(tmp)


def _stage_draft(tmp: Path, task_id: str = _TASK) -> DraftRef:
    ref = DraftRef(backend="strapi", content_type=ContentType.BLOG, ref_id="doc9", url="u://doc9")
    CmsDraftIndex(tmp / ".harness" / "cms-drafts.json").record(f"blog:{task_id}", ref)
    return ref


def _open_gate(ledger: SqliteLedger, approval_id: str = "apr_1", task_id: str = _TASK) -> None:
    ledger.approvals.request(
        Approval(
            id=approval_id,
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=task_id,
            reason="go-live publish to blog (content_draft.md)",
            gate_kind=ApprovalGate.AUTHORIZATION,
        )
    )


def _run(tool: ExecuteGoLiveTool, payload: dict[str, object], tmp: Path) -> Any:
    return asyncio.run(tool.execute(dict(payload), _ctx(tmp)))


_PUBLISH = {"content_type": "blog"}


class TestFailClosed:
    def test_no_beat_context_rejected(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        backend = _FakeBackend()
        res = _run(ExecuteGoLiveTool(ledger, backend), _PUBLISH, tmp_path)
        assert res.is_error is True
        assert backend.published == []

    def test_no_gate_at_all_rejected(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        _wire_beat(tmp_path)
        _stage_draft(tmp_path)
        backend = _FakeBackend()
        res = _run(ExecuteGoLiveTool(ledger, backend), _PUBLISH, tmp_path)
        assert res.is_error is True
        assert "stage_go_live" in res.content
        assert backend.published == []

    def test_pending_gate_rejected(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        _wire_beat(tmp_path)
        _stage_draft(tmp_path)
        _open_gate(ledger)  # left pending
        backend = _FakeBackend()
        res = _run(ExecuteGoLiveTool(ledger, backend), _PUBLISH, tmp_path)
        assert res.is_error is True
        assert "pending" in res.content.lower()
        assert backend.published == []

    def test_denied_gate_rejected(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        _wire_beat(tmp_path)
        _stage_draft(tmp_path)
        _open_gate(ledger)
        ledger.approvals.deny("apr_1", decided_by_user_id="boss")
        backend = _FakeBackend()
        res = _run(ExecuteGoLiveTool(ledger, backend), _PUBLISH, tmp_path)
        assert res.is_error is True
        assert "denied" in res.content.lower()
        assert backend.published == []

    def test_approval_id_for_another_task_rejected(
        self, ledger: SqliteLedger, tmp_path: Path
    ) -> None:
        _wire_beat(tmp_path)  # beat is task-1
        _stage_draft(tmp_path)
        _open_gate(ledger, approval_id="apr_other", task_id="SOMEONE-ELSES-TASK")
        ledger.approvals.approve("apr_other", decided_by_user_id="boss")
        backend = _FakeBackend()
        res = _run(
            ExecuteGoLiveTool(ledger, backend),
            {**_PUBLISH, "approval_id": "apr_other"},
            tmp_path,
        )
        assert res.is_error is True
        assert backend.published == []

    def test_approved_but_nothing_staged_rejected(
        self, ledger: SqliteLedger, tmp_path: Path
    ) -> None:
        _wire_beat(tmp_path)  # no cms draft staged
        _open_gate(ledger)
        ledger.approvals.approve("apr_1", decided_by_user_id="boss")
        backend = _FakeBackend()
        res = _run(ExecuteGoLiveTool(ledger, backend), _PUBLISH, tmp_path)
        assert res.is_error is True
        assert "cms_draft" in res.content
        assert backend.published == []


class TestApprovedExecutes:
    def test_approved_gate_publishes_the_standing_draft(
        self, ledger: SqliteLedger, tmp_path: Path
    ) -> None:
        _wire_beat(tmp_path)
        staged = _stage_draft(tmp_path)
        _open_gate(ledger)
        ledger.approvals.approve("apr_1", decided_by_user_id="boss")
        backend = _FakeBackend()

        res = _run(ExecuteGoLiveTool(ledger, backend), _PUBLISH, tmp_path)

        assert res.is_error is False
        assert backend.published == [staged]  # only the staged draft is publishable
        record = res.metadata["delivery"]
        assert record["approval_id"] == "apr_1"
        assert record["ref_id"] == "doc9"
        assert record["url"] == "live://doc9"
        # durable: the delivery index holds the standing record
        standing = DeliveryIndex(tmp_path / ".harness" / "deliveries.json").standing_delivery("apr_1")
        assert standing is not None and standing.published.ref_id == "doc9"

    def test_second_call_is_idempotent(self, ledger: SqliteLedger, tmp_path: Path) -> None:
        _wire_beat(tmp_path)
        _stage_draft(tmp_path)
        _open_gate(ledger)
        ledger.approvals.approve("apr_1", decided_by_user_id="boss")
        backend = _FakeBackend()
        tool = ExecuteGoLiveTool(ledger, backend)

        first = _run(tool, _PUBLISH, tmp_path)
        second = _run(tool, _PUBLISH, tmp_path)

        assert len(backend.published) == 1  # never double-publishes
        assert second.is_error is False
        assert "already" in second.content.lower()
        assert second.metadata["delivery"] == first.metadata["delivery"]

    def test_backend_failure_surfaces_recovery(
        self, ledger: SqliteLedger, tmp_path: Path
    ) -> None:
        _wire_beat(tmp_path)
        _stage_draft(tmp_path)
        _open_gate(ledger)
        ledger.approvals.approve("apr_1", decided_by_user_id="boss")

        res = _run(ExecuteGoLiveTool(ledger, _RaisingBackend()), _PUBLISH, tmp_path)

        assert res.is_error is True
        assert "boom" in res.content
        assert "root_cause" in res.content
        # nothing recorded — a failed publish leaves no standing delivery
        assert (
            DeliveryIndex(tmp_path / ".harness" / "deliveries.json").standing_delivery("apr_1")
            is None
        )


class TestInput:
    def test_input_requires_valid_content_type(self) -> None:
        with pytest.raises(Exception):
            ExecuteGoLiveInput(content_type="carrier-pigeon")  # type: ignore[arg-type]
