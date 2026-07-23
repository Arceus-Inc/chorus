"""`MarkdownPublishBackend` — the keyless publish: flip ``draft: true`` → ``draft: false``.

The exact static-site go-live mechanic (Hugo/Jekyll/Astro render a post the moment its frontmatter
stops saying draft), symmetric with :class:`~chorus_tools.cms.MarkdownCmsBackend` staging it. The
file is the one the DraftRef points at; a missing file raises :class:`DeliveryError` — there is
nothing staged to publish.
"""

from __future__ import annotations

from pathlib import Path

from chorus_tools._backends import BackendName
from chorus_tools.cms import DraftRef
from chorus_tools.delivery._types import DeliveryError, PublishedRef

_DRAFT_TRUE = "draft: true"
_DRAFT_FALSE = "draft: false"


class MarkdownPublishBackend:
    """Publish staged markdown drafts by flipping their frontmatter draft flag in place."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def publish(self, draft: DraftRef) -> PublishedRef:
        path = self._root / draft.ref_id
        if not path.is_file():
            raise DeliveryError(f"nothing staged to publish at {draft.ref_id!r}")
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(_DRAFT_TRUE, _DRAFT_FALSE, 1), encoding="utf-8")
        return PublishedRef(
            backend=BackendName.MARKDOWN.value, ref_id=draft.ref_id, url=path.as_uri()
        )


__all__ = ["MarkdownPublishBackend"]
