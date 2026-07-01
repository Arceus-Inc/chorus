"""MarkdownCmsBackend — the keyless default (design doc: backends).

Writes each draft as `{root}/{content_type}/{slug}.md` with `draft: true` frontmatter carrying every
field. Deterministic (same seed → same path), offline — the test default and a real static-site path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chorus_tools.cms import BlogDraft, ContentType, EmailDraft, SocialDraft, SocialPlatform
from chorus_tools.cms._markdown import MarkdownCmsBackend

pytestmark = pytest.mark.unit


def _front(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, front, *_ = text.split("---\n", 2)
    parsed = yaml.safe_load(front)
    assert isinstance(parsed, dict)
    return parsed


class TestMarkdownBackend:
    def test_blog_draft_writes_file_with_draft_frontmatter(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        ref = backend.create_draft(BlogDraft(title="Shipping safely", body="# Body\ncopy"))

        assert ref.backend == "markdown"
        assert ref.content_type is ContentType.BLOG
        assert ref.ref_id == "blog/shipping-safely.md"
        assert ref.status == "draft"
        assert ref.url.startswith("file://")

        path = tmp_path / "blog" / "shipping-safely.md"
        assert path.is_file()
        front = _front(path)
        assert front["draft"] is True
        assert front["content_type"] == "blog"
        assert front["title"] == "Shipping safely"
        assert front["body"] == "# Body\ncopy"

    def test_social_draft_routes_to_social_dir(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        ref = backend.create_draft(
            SocialDraft(platform=SocialPlatform.LINKEDIN, text="A concrete engineering moment")
        )
        assert ref.ref_id == "social/a-concrete-engineering-moment.md"
        front = _front(tmp_path / ref.ref_id)
        assert front["platform"] == "linkedin"
        assert front["text"] == "A concrete engineering moment"

    def test_email_draft_routes_to_email_dir(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        ref = backend.create_draft(EmailDraft(subject="Welcome to Arceus", body="body"))
        assert ref.ref_id == "email/welcome-to-arceus.md"
        front = _front(tmp_path / ref.ref_id)
        assert front["subject"] == "Welcome to Arceus"

    def test_slug_is_deterministic(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        a = backend.create_draft(BlogDraft(title="Same Title", body="one"))
        b = backend.create_draft(BlogDraft(title="Same Title!!!", body="two"))
        assert a.ref_id == b.ref_id  # punctuation-insensitive, same slug → same path (overwrite)

    def test_optional_fields_are_written(self, tmp_path: Path) -> None:
        backend = MarkdownCmsBackend(tmp_path)
        ref = backend.create_draft(
            BlogDraft(title="T", body="B", excerpt="short", seo_description="seo")
        )
        front = _front(tmp_path / ref.ref_id)
        assert front["excerpt"] == "short"
        assert front["seo_description"] == "seo"

    def test_blank_slug_seed_falls_back(self, tmp_path: Path) -> None:
        # A title that slugifies to nothing (all punctuation) still yields a stable filename.
        backend = MarkdownCmsBackend(tmp_path)
        ref = backend.create_draft(BlogDraft(title="!!!", body="B"))
        assert ref.ref_id == "blog/draft.md"
