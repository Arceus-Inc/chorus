"""CmsDraftTool — the `cms_draft` verb (design doc: the tool).

Validates a flat, channel-discriminated input into a typed draft, calls the injected backend, and
returns the observation/recovery contract. Backend is a fake here — the real ones are tested apart.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from chorus_tools.cms import BlogDraft, CmsError, ContentType, DraftRef, EmailDraft, SocialDraft
from chorus_tools.cms._tool import CmsDraftInput, CmsDraftTool

pytestmark = pytest.mark.unit


class _FakeBackend:
    def __init__(self) -> None:
        self.received: Any = None
        self.creates: list[Any] = []
        self.updates: list[tuple[str, Any]] = []

    def create_draft(self, draft: Any) -> DraftRef:
        self.received = draft
        self.creates.append(draft)
        ref_id = f"fake{len(self.creates)}"
        return DraftRef(
            backend="fake", content_type=draft.content_type, ref_id=ref_id, url=f"fake://{ref_id}"
        )

    def update_draft(self, ref_id: str, draft: Any) -> DraftRef:
        self.received = draft
        self.updates.append((ref_id, draft))
        return DraftRef(
            backend="fake", content_type=draft.content_type, ref_id=ref_id, url=f"fake://{ref_id}"
        )


class _RaisingBackend:
    def create_draft(self, draft: Any) -> DraftRef:
        raise CmsError("strapi 403: Forbidden")

    def update_draft(self, ref_id: str, draft: Any) -> DraftRef:
        raise CmsError("strapi 403: Forbidden")


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="s",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _run(tool: CmsDraftTool, payload: dict[str, object], tmp: Path) -> Any:
    return asyncio.run(tool.execute(dict(payload), _ctx(tmp)))


class TestDeclaration:
    def test_name_and_input_model(self) -> None:
        assert CmsDraftTool.name == "cms_draft"
        assert CmsDraftTool.input_model is CmsDraftInput

    def test_is_a_mutating_write(self) -> None:
        assert CmsDraftTool.declaration.risk == "mutating"


class TestExecute:
    def test_blog_success_routes_a_blog_draft(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        res = _run(
            CmsDraftTool(backend), {"content_type": "blog", "title": "T", "body": "B"}, tmp_path
        )
        assert res.is_error is False
        assert isinstance(backend.received, BlogDraft)
        assert backend.received.fields() == {"title": "T", "body": "B"}
        assert res.metadata["draft_ref"]["content_type"] == "blog"
        assert res.metadata["draft_ref"]["ref_id"] == "fake1"

    def test_social_routes_a_social_draft(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        _run(
            CmsDraftTool(backend),
            {"content_type": "social", "platform": "linkedin", "text": "hi"},
            tmp_path,
        )
        assert isinstance(backend.received, SocialDraft)
        assert backend.received.content_type is ContentType.SOCIAL

    def test_email_routes_an_email_draft(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        _run(
            CmsDraftTool(backend), {"content_type": "email", "subject": "S", "body": "B"}, tmp_path
        )
        assert isinstance(backend.received, EmailDraft)

    def test_success_next_actions_point_at_go_live(self, tmp_path: Path) -> None:
        res = _run(
            CmsDraftTool(_FakeBackend()),
            {"content_type": "blog", "title": "T", "body": "B"},
            tmp_path,
        )
        assert any("stage_go_live" in a for a in res.metadata["next_actions"])

    def test_missing_required_field_is_rejected_without_a_write(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        res = _run(
            CmsDraftTool(backend), {"content_type": "blog", "title": "T"}, tmp_path
        )  # no body
        assert res.is_error is True
        assert "root_cause" in res.content
        assert backend.received is None  # nothing was drafted

    def test_social_without_platform_is_rejected(self, tmp_path: Path) -> None:
        res = _run(CmsDraftTool(_FakeBackend()), {"content_type": "social", "text": "hi"}, tmp_path)
        assert res.is_error is True

    def test_backend_failure_is_surfaced_with_recovery(self, tmp_path: Path) -> None:
        res = _run(
            CmsDraftTool(_RaisingBackend()),
            {"content_type": "blog", "title": "T", "body": "B"},
            tmp_path,
        )
        assert res.is_error is True
        assert "Forbidden" in res.content
        assert "root_cause" in res.content


class TestInput:
    def test_to_draft_builds_the_right_type(self) -> None:
        assert isinstance(
            CmsDraftInput(content_type=ContentType.BLOG, title="T", body="B").to_draft(), BlogDraft
        )
        assert isinstance(
            CmsDraftInput(content_type=ContentType.EMAIL, subject="S", body="B").to_draft(),
            EmailDraft,
        )


def _write_beat_context(working_dir: Path, task_id: str) -> None:
    from chorus.heartbeat import BeatContext

    BeatContext(task_id=task_id, run_id="r1", employee_id="mira").write(working_dir)


class TestIdempotency:
    def test_repeat_same_task_and_type_updates_not_duplicates(self, tmp_path: Path) -> None:
        _write_beat_context(tmp_path, "task-1")
        backend = _FakeBackend()
        tool = CmsDraftTool(backend)
        r1 = _run(tool, {"content_type": "blog", "title": "T", "body": "v1"}, tmp_path)
        r2 = _run(tool, {"content_type": "blog", "title": "T", "body": "v2"}, tmp_path)
        assert len(backend.creates) == 1  # created once
        assert len(backend.updates) == 1  # then updated in place
        assert r1.metadata["draft_ref"]["ref_id"] == r2.metadata["draft_ref"]["ref_id"]

    def test_different_content_type_same_task_is_a_separate_draft(self, tmp_path: Path) -> None:
        _write_beat_context(tmp_path, "task-1")
        backend = _FakeBackend()
        tool = CmsDraftTool(backend)
        _run(tool, {"content_type": "blog", "title": "T", "body": "B"}, tmp_path)
        _run(tool, {"content_type": "social", "platform": "linkedin", "text": "hi"}, tmp_path)
        assert len(backend.creates) == 2  # blog and social are distinct deliverables
        assert backend.updates == []

    def test_without_beat_context_each_call_creates(self, tmp_path: Path) -> None:
        # No .harness/beat-context.json → no idempotency key → plain create each time (unchanged default).
        backend = _FakeBackend()
        tool = CmsDraftTool(backend)
        _run(tool, {"content_type": "blog", "title": "T", "body": "v1"}, tmp_path)
        _run(tool, {"content_type": "blog", "title": "T", "body": "v2"}, tmp_path)
        assert len(backend.creates) == 2
        assert backend.updates == []
