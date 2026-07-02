"""`MarkdownCmsBackend` — the keyless default backend (design doc: backends).

Writes each draft as a static-site-style markdown file — `{root}/{content_type}/{slug}.md` with YAML
frontmatter carrying `draft: true`, the `content_type`, and every field. No network, no keys: this is
both the deterministic test default and a genuine git/markdown publishing path (a `draft: true` post
is exactly how Hugo/Jekyll/Astro model an unpublished draft).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from chorus_tools._backends import BackendName
from chorus_tools.cms._types import (
    CmsDraft,
    CmsError,
    ContentType,
    DraftRef,
    draft_from_fields,
)

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 60
_SLUG_FALLBACK = "draft"


class MarkdownCmsBackend:
    """Persist drafts as `draft: true` markdown files under a content root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def create_draft(self, draft: CmsDraft) -> DraftRef:
        relative = Path(draft.content_type.value) / f"{_slugify(draft.slug_seed())}.md"
        return self._write(relative, draft)

    def update_draft(self, ref_id: str, draft: CmsDraft) -> DraftRef:
        """Overwrite the standing draft at ``ref_id`` (a stable path — the title may have changed)."""
        return self._write(Path(ref_id), draft)

    def read_draft(self, ref_id: str, content_type: ContentType) -> CmsDraft:
        """Rebuild the staged draft from its frontmatter — the send path reads APPROVED content."""
        path = self._root / ref_id
        if not path.is_file():
            raise CmsError(f"no staged draft at {ref_id!r}")
        return draft_from_fields(
            content_type, _frontmatter(path.read_text(encoding="utf-8"), ref_id)
        )

    def _write(self, relative: Path, draft: CmsDraft) -> DraftRef:
        path = self._root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(draft), encoding="utf-8")
        return DraftRef(
            backend=BackendName.MARKDOWN.value,
            content_type=draft.content_type,
            ref_id=str(relative),
            url=path.as_uri(),
        )


def _render(draft: CmsDraft) -> str:
    """Render a draft as frontmatter (`draft: true` + content_type + fields), empty body below."""
    front: dict[str, object] = {"draft": True, "content_type": draft.content_type.value}
    front.update(draft.fields())
    dumped = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"---\n{dumped}\n---\n"


def _frontmatter(text: str, ref_id: str) -> dict[str, object]:
    """The YAML frontmatter map of a staged file; a file without one raises :class:`CmsError`."""
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if match is None:
        raise CmsError(f"staged draft {ref_id!r} has no frontmatter")
    loaded = yaml.safe_load(match.group(1))
    if not isinstance(loaded, dict):
        raise CmsError(f"staged draft {ref_id!r} has malformed frontmatter")
    return loaded


def _slugify(seed: str) -> str:
    """Lowercase, collapse non-alphanumerics to single dashes, trim, cap length; fallback if empty."""
    slug = _NON_SLUG.sub("-", seed.lower()).strip("-")[:_SLUG_MAX].strip("-")
    return slug or _SLUG_FALLBACK


__all__ = ["MarkdownCmsBackend"]
