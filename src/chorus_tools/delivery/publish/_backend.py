"""The `PublishBackend` seam — the one operation a publish executor implements.

Turns a staged :class:`~chorus_tools.cms.DraftRef` into LIVE content and reports where it landed.
Implementations: :class:`~chorus_tools.delivery.publish._strapi.StrapiPublishBackend` (hosted) and
:class:`~chorus_tools.delivery.publish._markdown.MarkdownPublishBackend` (keyless static-site flip).
The `email.send` executor's ``EmailBackend`` will sit beside this seam in a later slice.
"""

from __future__ import annotations

from typing import Protocol

from chorus_tools.cms import DraftRef
from chorus_tools.delivery._types import PublishedRef


class PublishBackend(Protocol):
    """Publish a staged draft; raise :class:`DeliveryError` on failure."""

    def publish(self, draft: DraftRef) -> PublishedRef: ...


__all__ = ["PublishBackend"]
