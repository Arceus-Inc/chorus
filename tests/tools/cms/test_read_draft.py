"""CmsBackend.read_draft — the inverse of staging (email-send design: cms additions).

At execute time the send executor reads the STAGED draft back and sends that — the model can never
smuggle different copy past the gate. Round-trip per backend; unknown/malformed → CmsError.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from chorus_tools.cms import (
    BlogDraft,
    CmsError,
    ContentType,
    EmailDraft,
    MarkdownCmsBackend,
    SocialDraft,
    SocialPlatform,
    StrapiCmsBackend,
)

pytestmark = pytest.mark.unit

_BASE = "http://localhost:1337"
_TOKEN = "test-token"


class TestMarkdownReadDraft:
    def test_email_round_trip(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        draft = EmailDraft(subject="Launch news", body="Hello!", preheader="pre", segment="beta")
        ref = backend.create_draft(draft)
        assert backend.read_draft(ref.ref_id, ContentType.EMAIL) == draft

    def test_blog_round_trip(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        draft = BlogDraft(title="T", body="B", excerpt="E")
        ref = backend.create_draft(draft)
        assert backend.read_draft(ref.ref_id, ContentType.BLOG) == draft

    def test_social_round_trip(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        draft = SocialDraft(platform=SocialPlatform.LINKEDIN, text="hi", link="https://x.y")
        ref = backend.create_draft(draft)
        assert backend.read_draft(ref.ref_id, ContentType.SOCIAL) == draft

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CmsError, match=r"ghost\.md"):
            MarkdownCmsBackend(tmp_path).read_draft("email/ghost.md", ContentType.EMAIL)

    def test_malformed_frontmatter_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "email" / "bad.md"
        path.parent.mkdir(parents=True)
        path.write_text("no frontmatter here", encoding="utf-8")
        with pytest.raises(CmsError, match="frontmatter"):
            MarkdownCmsBackend(tmp_path).read_draft("email/bad.md", ContentType.EMAIL)


def _strapi(handler: Any) -> StrapiCmsBackend:
    return StrapiCmsBackend(
        _BASE, _TOKEN, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


class TestStrapiReadDraft:
    def test_email_read_hits_draft_endpoint_and_maps_fields(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            handler.request = request  # type: ignore[attr-defined]
            return httpx.Response(200, json={"data": {
                "documentId": "doc7", "subject": "Launch news", "body": "Hello!",
                "preheader": "pre", "segment": "beta", "publishedAt": None,
            }})

        backend = _strapi(handler)
        draft = backend.read_draft("doc7", ContentType.EMAIL)

        req: httpx.Request = handler.request  # type: ignore[attr-defined]
        assert req.method == "GET"
        assert req.url.path == "/api/email-campaigns/doc7"
        assert req.url.params.get("status") == "draft"
        assert req.headers["authorization"] == f"Bearer {_TOKEN}"
        assert draft == EmailDraft(subject="Launch news", body="Hello!", preheader="pre", segment="beta")

    def test_null_optional_fields_become_defaults(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {
                "documentId": "doc7", "subject": "S", "body": "B",
                "preheader": None, "segment": None,
            }})

        draft = _strapi(handler).read_draft("doc7", ContentType.EMAIL)
        assert draft == EmailDraft(subject="S", body="B")

    def test_not_found_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"message": "Not Found"}})

        with pytest.raises(CmsError, match="404"):
            _strapi(handler).read_draft("nope", ContentType.EMAIL)

    def test_missing_required_field_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"documentId": "doc7", "body": "B"}})

        with pytest.raises(CmsError, match="subject"):
            _strapi(handler).read_draft("doc7", ContentType.EMAIL)
