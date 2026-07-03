"""Publish backends — Strapi (draft→published flip) and Markdown (frontmatter flip).

Strapi contract (pinned live 2026-07-02): ``PUT /api/{collection}/{documentId}?status=published``
with ``{"data": {}}`` publishes the existing draft, fields preserved. Blog content publishes to the
public blog URL. Markdown publish flips ``draft: true`` → ``draft: false`` in place — exactly how a
static site goes live.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from chorus_tools.cms import BlogDraft, ContentType, DraftRef, MarkdownCmsBackend
from chorus_tools.delivery import DeliveryError, PublishedRef
from chorus_tools.delivery._config import publish_backend_from_env
from chorus_tools.delivery.publish import MarkdownPublishBackend, StrapiPublishBackend

pytestmark = pytest.mark.unit

_BASE = "http://localhost:1337"
_TOKEN = "test-token"


def _backend(handler: Any) -> StrapiPublishBackend:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return StrapiPublishBackend(_BASE, _TOKEN, client=client)


def _ok(document_id: str = "doc9") -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request  # type: ignore[attr-defined]
        return httpx.Response(
            200, json={"data": {"documentId": document_id, "publishedAt": "2026-07-02T00:00:00Z"}}
        )

    return handler


def _blog_ref(ref_id: str = "doc9") -> DraftRef:
    return DraftRef(backend="strapi", content_type=ContentType.BLOG, ref_id=ref_id, url="u://x")


class TestStrapiPublish:
    def test_puts_status_published_with_empty_data(self) -> None:
        handler = _ok()
        published = _backend(handler).publish(_blog_ref())

        req: httpx.Request = handler.request
        assert req.method == "PUT"
        assert req.url.path == "/api/blog-posts/doc9"
        assert req.url.params.get("status") == "published"
        assert req.headers["authorization"] == f"Bearer {_TOKEN}"
        assert json.loads(req.content) == {"data": {}}
        assert isinstance(published, PublishedRef)
        assert published.backend == "strapi"
        assert published.ref_id == "doc9"

    def test_blog_publishes_to_the_public_blog_url(self) -> None:
        published = _backend(_ok("abc")).publish(_blog_ref("abc"))
        assert published.url == f"{_BASE}/blog/#/post/abc"

    def test_non_blog_publishes_to_the_admin_url(self) -> None:
        social = DraftRef(
            backend="strapi", content_type=ContentType.SOCIAL, ref_id="s1", url="u://x"
        )
        published = _backend(_ok("s1")).publish(social)
        assert "content-manager" in published.url and "s1" in published.url

    def test_non_2xx_raises_delivery_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"message": "Not Found"}})

        with pytest.raises(DeliveryError, match="404"):
            _backend(handler).publish(_blog_ref())

    def test_missing_document_id_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {}})

        with pytest.raises(DeliveryError, match="documentId"):
            _backend(handler).publish(_blog_ref())

    def test_error_does_not_leak_the_provider_body(self) -> None:
        # The provider body can echo tenant/address/field detail; it must stay server-side and
        # never ride into the model-visible exception. Only the HTTP status class is surfaced.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, text="secret-tenant-xyz validation of 'from' failed")

        with pytest.raises(DeliveryError) as exc_info:
            _backend(handler).publish(_blog_ref())
        message = str(exc_info.value)
        assert "422" in message
        assert "secret-tenant-xyz" not in message

    def test_non_json_2xx_raises_delivery_error_not_decode_error(self) -> None:
        # A 2xx with a non-JSON body must surface as the domain error (caught by the tool's
        # recovery contract), never an unchained JSONDecodeError that escapes the tool.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>gateway</html>")

        with pytest.raises(DeliveryError):
            _backend(handler).publish(_blog_ref())


class TestMarkdownPublish:
    def test_flips_draft_true_to_false_in_place(self, tmp_path: Path) -> None:
        # Stage a draft with the cms backend, then publish it with the delivery backend.
        draft_ref = MarkdownCmsBackend(tmp_path).create_draft(BlogDraft(title="T", body="B"))
        path = tmp_path / draft_ref.ref_id
        assert "draft: true" in path.read_text(encoding="utf-8")

        published = MarkdownPublishBackend(tmp_path).publish(draft_ref)

        text = path.read_text(encoding="utf-8")
        assert "draft: false" in text
        assert "draft: true" not in text
        assert published.backend == "markdown"
        assert published.ref_id == draft_ref.ref_id

    def test_missing_file_raises_delivery_error(self, tmp_path: Path) -> None:
        ghost = DraftRef(
            backend="markdown", content_type=ContentType.BLOG, ref_id="blog/nope.md", url="u://x"
        )
        with pytest.raises(DeliveryError, match=r"nope\.md"):
            MarkdownPublishBackend(tmp_path).publish(ghost)


class TestPublishBackendFromEnv:
    def test_markdown_when_strapi_env_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("STRAPI_URL", raising=False)
        monkeypatch.delenv("STRAPI_TOKEN", raising=False)
        assert isinstance(publish_backend_from_env(tmp_path), MarkdownPublishBackend)

    def test_strapi_when_env_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRAPI_URL", _BASE)
        monkeypatch.setenv("STRAPI_TOKEN", "tok")
        assert isinstance(publish_backend_from_env(tmp_path), StrapiPublishBackend)
