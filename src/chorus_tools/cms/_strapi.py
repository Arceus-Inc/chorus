"""`StrapiCmsBackend` — the hosted backend, over Strapi v5's REST content API (design doc: backends).

Routes a draft's `content_type` to its collection and `POST`s `?status=draft` with a Bearer token —
the `?status=draft` param is REQUIRED (a plain POST auto-publishes). The `documentId` from the
response becomes the `DraftRef`. The `httpx.Client` is injected so tests drive it with a
`MockTransport` and no network. A non-2xx or a response missing `documentId` raises :class:`CmsError`.
"""

from __future__ import annotations

import httpx

from chorus_tools.cms._types import CmsDraft, CmsError, ContentType, DraftRef

# content_type -> (plural collection id, singular id) — the Strapi types built during setup.
_COLLECTIONS: dict[ContentType, tuple[str, str]] = {
    ContentType.BLOG: ("blog-posts", "blog-post"),
    ContentType.SOCIAL: ("social-posts", "social-post"),
    ContentType.EMAIL: ("email-campaigns", "email-campaign"),
}


class StrapiCmsBackend:
    """Create Strapi drafts via the REST content API with an injected :class:`httpx.Client`."""

    def __init__(self, base_url: str, token: str, *, client: httpx.Client) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._client = client

    def create_draft(self, draft: CmsDraft) -> DraftRef:
        collection, _ = _COLLECTIONS[draft.content_type]
        response = self._client.post(
            f"{self._base}/api/{collection}",
            params={"status": "draft"},
            headers={"Authorization": f"Bearer {self._token}"},
            json={"data": draft.fields()},
        )
        return self._ref_from(response, draft)

    def update_draft(self, ref_id: str, draft: CmsDraft) -> DraftRef:
        """Update the standing draft ``ref_id`` in place (PUT ?status=draft) — no duplicate entry."""
        collection, _ = _COLLECTIONS[draft.content_type]
        response = self._client.put(
            f"{self._base}/api/{collection}/{ref_id}",
            params={"status": "draft"},
            headers={"Authorization": f"Bearer {self._token}"},
            json={"data": draft.fields()},
        )
        return self._ref_from(response, draft)

    def _ref_from(self, response: httpx.Response, draft: CmsDraft) -> DraftRef:
        if response.status_code // 100 != 2:
            raise CmsError(f"strapi {response.status_code}: {response.text[:200]}")
        _, singular = _COLLECTIONS[draft.content_type]
        document_id = _document_id(response)
        return DraftRef(
            backend="strapi",
            content_type=draft.content_type,
            ref_id=document_id,
            url=(
                f"{self._base}/admin/content-manager/collection-types/"
                f"api::{singular}.{singular}/{document_id}"
            ),
        )


def _document_id(response: httpx.Response) -> str:
    """Pull `data.documentId` from a Strapi create response, or raise :class:`CmsError`."""
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    document_id = data.get("documentId") if isinstance(data, dict) else None
    if not isinstance(document_id, str) or not document_id:
        raise CmsError("strapi response missing data.documentId")
    return document_id


__all__ = ["StrapiCmsBackend"]
