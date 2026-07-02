"""The `CmsBackend` seam — the one operation every CMS target implements.

A backend turns a validated :class:`~chorus_tools.cms._types.CmsDraft` into a reversible draft and
returns a :class:`~chorus_tools.cms._types.DraftRef`. Implementations: the keyless
:class:`~chorus_tools.cms._markdown.MarkdownCmsBackend` and the hosted
:class:`~chorus_tools.cms._strapi.StrapiCmsBackend`. The verb is unchanged across backends — only the
source swaps (design doc: backends).
"""

from __future__ import annotations

from typing import Protocol

from chorus_tools.cms._types import CmsDraft, ContentType, DraftRef


class CmsBackend(Protocol):
    """Create/update a reversible draft from a validated :class:`CmsDraft`; raise ``CmsError`` on failure."""

    def create_draft(self, draft: CmsDraft) -> DraftRef: ...

    def update_draft(self, ref_id: str, draft: CmsDraft) -> DraftRef:
        """Update the standing draft ``ref_id`` in place — the idempotent re-stage path."""
        ...

    def read_draft(self, ref_id: str, content_type: ContentType) -> CmsDraft:
        """Rebuild the staged draft — the send executor reads APPROVED content, never model input."""
        ...


__all__ = ["CmsBackend"]
