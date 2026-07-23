"""`StrapiPublishBackend` — flip a staged Strapi draft to PUBLISHED (design doc: backends).

Contract pinned live against the local instance (2026-07-02):
``PUT /api/{collection}/{documentId}?status=published`` with body ``{"data": {}}`` publishes the
existing draft — fields preserved, ``publishedAt`` set, entry immediately visible on the public
API. For blog content that means the post appears on the public blog; the returned URL points a
human straight at it. Injected :class:`httpx.Client` (MockTransport-tested); non-2xx or a missing
``documentId`` raises :class:`DeliveryError`.
"""

from __future__ import annotations

import httpx

from chorus_tools._backends import BackendName
from chorus_tools._http import ensure_ok, strapi_document_id
from chorus_tools.cms import ContentType, DraftRef
from chorus_tools.delivery._types import DeliveryError, PublishedRef

# content_type -> (plural collection id, singular id) — same map as the cms Strapi backend.
_COLLECTIONS: dict[ContentType, tuple[str, str]] = {
    ContentType.BLOG: ("blog-posts", "blog-post"),
    ContentType.SOCIAL: ("social-posts", "social-post"),
    ContentType.EMAIL: ("email-campaigns", "email-campaign"),
}


class StrapiPublishBackend:
    """Publish staged Strapi drafts via the REST content API with an injected client."""

    def __init__(self, base_url: str, token: str, *, client: httpx.Client) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._client = client

    def publish(self, draft: DraftRef) -> PublishedRef:
        collection, singular = _COLLECTIONS[draft.content_type]
        response = self._client.put(
            f"{self._base}/api/{collection}/{draft.ref_id}",
            params={"status": "published"},
            headers={"Authorization": f"Bearer {self._token}"},
            json={"data": {}},  # publish the existing draft content verbatim
        )
        ensure_ok(response, prefix="strapi publish", error=DeliveryError)
        document_id = strapi_document_id(response, prefix="strapi publish", error=DeliveryError)
        return PublishedRef(
            backend=BackendName.STRAPI.value,
            ref_id=document_id,
            url=self._live_url(draft.content_type, singular, document_id),
        )

    def _live_url(self, content_type: ContentType, singular: str, document_id: str) -> str:
        """Where a human sees the LIVE content — the public blog for blog posts, admin otherwise."""
        if content_type is ContentType.BLOG:
            return f"{self._base}/blog/#/post/{document_id}"
        return (
            f"{self._base}/admin/content-manager/collection-types/"
            f"api::{singular}.{singular}/{document_id}"
        )


__all__ = ["StrapiPublishBackend"]
