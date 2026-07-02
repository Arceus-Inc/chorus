"""`StrapiCmsBackend` — the hosted backend, over Strapi v5's REST content API (design doc: backends).

Routes a draft's `content_type` to its collection and `POST`s `?status=draft` with a Bearer token —
the `?status=draft` param is REQUIRED (a plain POST auto-publishes). The `documentId` from the
response becomes the `DraftRef`. The `httpx.Client` is injected so tests drive it with a
`MockTransport` and no network. A non-2xx or a response missing `documentId` raises :class:`CmsError`.
"""

from __future__ import annotations

import httpx

from chorus_tools._backends import BackendName
from chorus_tools._http import ensure_ok, json_body, strapi_document_id
from chorus_tools.cms._types import CmsDraft, CmsError, ContentType, DraftRef, draft_from_fields

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

    def read_draft(self, ref_id: str, content_type: ContentType) -> CmsDraft:
        """Rebuild the staged draft from Strapi — the send path reads APPROVED content, never input."""
        collection, _ = _COLLECTIONS[content_type]
        response = self._client.get(
            f"{self._base}/api/{collection}/{ref_id}",
            params={"status": "draft"},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        ensure_ok(response, prefix="strapi read", error=CmsError)
        payload = json_body(response, prefix="strapi read", error=CmsError)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise CmsError("strapi read: response missing data")
        return draft_from_fields(content_type, data)

    def _ref_from(self, response: httpx.Response, draft: CmsDraft) -> DraftRef:
        ensure_ok(response, prefix="strapi", error=CmsError)
        _, singular = _COLLECTIONS[draft.content_type]
        document_id = strapi_document_id(response, prefix="strapi", error=CmsError)
        return DraftRef(
            backend=BackendName.STRAPI.value,
            content_type=draft.content_type,
            ref_id=document_id,
            url=(
                f"{self._base}/admin/content-manager/collection-types/"
                f"api::{singular}.{singular}/{document_id}"
            ),
        )


__all__ = ["StrapiCmsBackend"]
