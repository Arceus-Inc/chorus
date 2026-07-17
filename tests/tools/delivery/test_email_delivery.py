"""EmailDelivery + the tool's send branch — the approved DRAFT content sends, never model input.

EmailDelivery is the one place content meets transport: read the staged draft back from the CMS,
compose it onto the configured routing, hand it to the email backend. The tool routes
content_type=email through it and records the delivery as action=send.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import Approval, ApprovalGate, ApprovalSubjectKind, Ledger
from chorus.testing import uid
from chorus_tools.cms import ContentType, DraftRef, EmailDraft, MarkdownCmsBackend
from chorus_tools.cms._index import CmsDraftIndex
from chorus_tools.delivery import DeliveryError, PublishedRef
from chorus_tools.delivery._tool import ExecuteGoLiveTool
from chorus_tools.delivery.email import EmailDelivery, EmailMessage, EmailRouting

pytestmark = pytest.mark.integration

_TASK = "task-1"
_ROUTING = EmailRouting(sender="mira@arceus.sh", recipients=("board@arceus.sh",))


class _FakeTransport:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage, *, idempotency_key: str) -> PublishedRef:
        self.sent.append(message)
        self.idempotency_key = idempotency_key
        return PublishedRef(backend="fake-esp", ref_id=uid("msg_1"), url="esp://msg_1")


class _FakePublish:
    def publish(self, draft: DraftRef) -> PublishedRef:
        raise AssertionError("publish must not be called for an email send")


def _ctx(working_dir: Path) -> Any:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id=uid("s"),
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


class TestEmailDelivery:
    def test_sends_the_staged_content_on_the_configured_route(self, tmp_path: Path) -> None:
        cms = MarkdownCmsBackend(tmp_path)
        staged = cms.create_draft(EmailDraft(subject="Launch news", body="Hello!", preheader="pre"))
        transport = _FakeTransport()

        landed = EmailDelivery(cms, transport, _ROUTING).send(staged, idempotency_key=uid("apr_1"))

        assert transport.sent == [
            EmailMessage(
                sender="mira@arceus.sh",
                recipients=("board@arceus.sh",),
                subject="Launch news",
                body="Hello!",
                preheader="pre",
            )
        ]
        assert landed.ref_id == uid("msg_1")

    def test_missing_staged_draft_raises_delivery_error(self, tmp_path: Path) -> None:
        ghost = DraftRef(
            backend="markdown", content_type=ContentType.EMAIL, ref_id="email/ghost.md", url="u://x"
        )
        with pytest.raises(DeliveryError, match="staged"):
            EmailDelivery(MarkdownCmsBackend(tmp_path), _FakeTransport(), _ROUTING).send(
                ghost, idempotency_key=uid("apr_1")
            )

    def test_non_email_draft_rejected(self, tmp_path: Path) -> None:
        blog = DraftRef(
            backend="markdown", content_type=ContentType.BLOG, ref_id="blog/x.md", url="u://x"
        )
        with pytest.raises(DeliveryError, match="email"):
            EmailDelivery(MarkdownCmsBackend(tmp_path), _FakeTransport(), _ROUTING).send(
                blog, idempotency_key=uid("apr_1")
            )


def _approved_email_stage(ledger: Ledger, tmp: Path) -> DraftRef:
    """A staged email draft + an APPROVED gate for the beat's task."""
    BeatContext(task_id=_TASK, run_id=uid("r1"), employee_id="mira").write(tmp)
    staged = MarkdownCmsBackend(tmp).create_draft(EmailDraft(subject="Launch news", body="Hello!"))
    CmsDraftIndex(tmp / ".harness" / "cms-drafts.json").record(f"email:{_TASK}", staged)
    ledger.approvals.request(
        Approval(
            id=uid("apr_1"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=_TASK,
            reason="go-live send to board",
            gate_kind=ApprovalGate.AUTHORIZATION,
        )
    )
    ledger.approvals.approve(uid("apr_1"), decided_by_user_id="boss")
    return staged


class TestToolSendBranch:
    def test_email_content_type_routes_to_send(self, ledger: Ledger, tmp_path: Path) -> None:
        _approved_email_stage(ledger, tmp_path)
        transport = _FakeTransport()
        delivery = EmailDelivery(MarkdownCmsBackend(tmp_path), transport, _ROUTING)
        tool = ExecuteGoLiveTool(ledger, _FakePublish(), email_delivery=delivery)

        res = asyncio.run(tool.execute({"content_type": "email"}, _ctx(tmp_path)))

        assert res.is_error is False
        assert len(transport.sent) == 1
        assert transport.idempotency_key == uid("apr_1")  # the tool keys the send on the gate id
        record = res.metadata["delivery"]
        assert record["action"] == "send"
        assert record["backend"] == "fake-esp"

    def test_email_without_configured_delivery_rejected(
        self, ledger: Ledger, tmp_path: Path
    ) -> None:
        _approved_email_stage(ledger, tmp_path)
        tool = ExecuteGoLiveTool(ledger, _FakePublish())  # no email delivery wired

        res = asyncio.run(tool.execute({"content_type": "email"}, _ctx(tmp_path)))

        assert res.is_error is True
        assert "email" in res.content.lower()

    def test_send_failure_warns_about_the_at_most_once_window(
        self, ledger: Ledger, tmp_path: Path
    ) -> None:
        # A send has no idempotent record until it succeeds, so the transport may already have
        # accepted the message before failing. The recovery guidance must NOT say "retry once"
        # (that risks a double-send); it must warn the send may already have gone out.
        _approved_email_stage(ledger, tmp_path)

        class _RaisingTransport:
            def send(self, message: EmailMessage, *, idempotency_key: str) -> PublishedRef:
                raise DeliveryError("resend send: HTTP 504")

        delivery = EmailDelivery(MarkdownCmsBackend(tmp_path), _RaisingTransport(), _ROUTING)
        tool = ExecuteGoLiveTool(ledger, _FakePublish(), email_delivery=delivery)

        res = asyncio.run(tool.execute({"content_type": "email"}, _ctx(tmp_path)))

        assert res.is_error is True
        assert "retry once" not in res.content
        assert "already" in res.content.lower()  # the send may already have been delivered

    def test_send_is_idempotent_per_approval(self, ledger: Ledger, tmp_path: Path) -> None:
        _approved_email_stage(ledger, tmp_path)
        transport = _FakeTransport()
        delivery = EmailDelivery(MarkdownCmsBackend(tmp_path), transport, _ROUTING)
        tool = ExecuteGoLiveTool(ledger, _FakePublish(), email_delivery=delivery)

        first = asyncio.run(tool.execute({"content_type": "email"}, _ctx(tmp_path)))
        second = asyncio.run(tool.execute({"content_type": "email"}, _ctx(tmp_path)))

        assert len(transport.sent) == 1  # never double-sends
        assert second.metadata["delivery"] == first.metadata["delivery"]
