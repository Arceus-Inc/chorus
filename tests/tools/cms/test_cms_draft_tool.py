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

    def create_draft(self, draft: Any) -> DraftRef:
        self.received = draft
        return DraftRef(backend="fake", content_type=draft.content_type, ref_id="fake1", url="fake://1")


class _RaisingBackend:
    def create_draft(self, draft: Any) -> DraftRef:
        raise CmsError("strapi 403: Forbidden")


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir, session_id="s", metadata={}, scratch_dir=working_dir,
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
        res = _run(CmsDraftTool(backend), {"content_type": "blog", "title": "T", "body": "B"}, tmp_path)
        assert res.is_error is False
        assert isinstance(backend.received, BlogDraft)
        assert backend.received.fields() == {"title": "T", "body": "B"}
        assert res.metadata["draft_ref"]["content_type"] == "blog"
        assert res.metadata["draft_ref"]["ref_id"] == "fake1"

    def test_social_routes_a_social_draft(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        _run(CmsDraftTool(backend), {"content_type": "social", "platform": "linkedin", "text": "hi"}, tmp_path)
        assert isinstance(backend.received, SocialDraft)
        assert backend.received.content_type is ContentType.SOCIAL

    def test_email_routes_an_email_draft(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        _run(CmsDraftTool(backend), {"content_type": "email", "subject": "S", "body": "B"}, tmp_path)
        assert isinstance(backend.received, EmailDraft)

    def test_success_next_actions_point_at_go_live(self, tmp_path: Path) -> None:
        res = _run(CmsDraftTool(_FakeBackend()), {"content_type": "blog", "title": "T", "body": "B"}, tmp_path)
        assert any("stage_go_live" in a for a in res.metadata["next_actions"])

    def test_missing_required_field_is_rejected_without_a_write(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        res = _run(CmsDraftTool(backend), {"content_type": "blog", "title": "T"}, tmp_path)  # no body
        assert res.is_error is True
        assert "root_cause" in res.content
        assert backend.received is None  # nothing was drafted

    def test_social_without_platform_is_rejected(self, tmp_path: Path) -> None:
        res = _run(CmsDraftTool(_FakeBackend()), {"content_type": "social", "text": "hi"}, tmp_path)
        assert res.is_error is True

    def test_backend_failure_is_surfaced_with_recovery(self, tmp_path: Path) -> None:
        res = _run(CmsDraftTool(_RaisingBackend()), {"content_type": "blog", "title": "T", "body": "B"}, tmp_path)
        assert res.is_error is True
        assert "Forbidden" in res.content
        assert "root_cause" in res.content


class TestInput:
    def test_to_draft_builds_the_right_type(self) -> None:
        assert isinstance(CmsDraftInput(content_type=ContentType.BLOG, title="T", body="B").to_draft(), BlogDraft)
        assert isinstance(CmsDraftInput(content_type=ContentType.EMAIL, subject="S", body="B").to_draft(), EmailDraft)
