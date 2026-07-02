"""StrapiCmsBackend — the hosted backend (design doc: backends).

Maps content_type → collection, POSTs `?status=draft` with a Bearer token, and parses `documentId`
into a DraftRef. Tested with `httpx.MockTransport` — the real HTTP shape asserted, zero network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from chorus_tools.cms import (
    BlogDraft,
    CmsError,
    ContentType,
    EmailDraft,
    SocialDraft,
    SocialPlatform,
)
from chorus_tools.cms._strapi import StrapiCmsBackend

pytestmark = pytest.mark.unit

_BASE = "http://localhost:1337"
_TOKEN = "test-token"


def _backend(handler: Any, base: str = _BASE) -> StrapiCmsBackend:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return StrapiCmsBackend(base, _TOKEN, client=client)


def _ok(document_id: str = "doc123") -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request  # type: ignore[attr-defined]
        return httpx.Response(201, json={"data": {"documentId": document_id, "publishedAt": None}})

    return handler


class TestStrapiCreateDraft:
    def test_blog_posts_to_the_right_collection_as_draft(self) -> None:
        handler = _ok()
        ref = _backend(handler).create_draft(BlogDraft(title="T", body="B"))

        req: httpx.Request = handler.request
        assert req.method == "POST"
        assert req.url.path == "/api/blog-posts"
        assert req.url.params.get("status") == "draft"
        assert req.headers["authorization"] == f"Bearer {_TOKEN}"
        assert json.loads(req.content) == {"data": {"title": "T", "body": "B"}}

        assert ref.backend == "strapi"
        assert ref.content_type is ContentType.BLOG
        assert ref.ref_id == "doc123"
        assert "doc123" in ref.url and "blog-post" in ref.url
        assert ref.status == "draft"

    def test_social_routes_to_social_posts(self) -> None:
        handler = _ok("s1")
        ref = _backend(handler).create_draft(
            SocialDraft(platform=SocialPlatform.LINKEDIN, text="hi")
        )
        assert handler.request.url.path == "/api/social-posts"
        assert json.loads(handler.request.content)["data"]["platform"] == "linkedin"
        assert ref.ref_id == "s1"

    def test_email_routes_to_email_campaigns(self) -> None:
        handler = _ok("e1")
        ref = _backend(handler).create_draft(EmailDraft(subject="S", body="B"))
        assert handler.request.url.path == "/api/email-campaigns"
        assert ref.ref_id == "e1"

    def test_base_url_trailing_slash_trimmed(self) -> None:
        handler = _ok()
        _backend(handler, base="http://localhost:1337/").create_draft(BlogDraft(title="T", body="B"))
        assert str(handler.request.url).startswith("http://localhost:1337/api/blog-posts")

    def test_non_2xx_raises_cms_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": {"message": "Forbidden"}})

        with pytest.raises(CmsError, match="403"):
            _backend(handler).create_draft(BlogDraft(title="T", body="B"))

    def test_2xx_without_document_id_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={"data": {}})

        with pytest.raises(CmsError, match="documentId"):
            _backend(handler).create_draft(BlogDraft(title="T", body="B"))


class TestStrapiUpdate:
    def test_update_puts_to_the_document_as_draft(self) -> None:
        handler = _ok("doc9")
        ref = _backend(handler).update_draft("doc9", BlogDraft(title="New", body="v2"))
        req: httpx.Request = handler.request
        assert req.method == "PUT"
        assert req.url.path == "/api/blog-posts/doc9"
        assert req.url.params.get("status") == "draft"
        assert json.loads(req.content) == {"data": {"title": "New", "body": "v2"}}
        assert ref.ref_id == "doc9"
        assert ref.content_type is ContentType.BLOG

    def test_update_non_2xx_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"message": "Not Found"}})

        with pytest.raises(CmsError, match="404"):
            _backend(handler).update_draft("gone", BlogDraft(title="T", body="B"))
