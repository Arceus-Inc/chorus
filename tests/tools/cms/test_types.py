"""cms.draft — the per-channel draft value types (design doc: content model).

Each channel is its own typed, frozen dataclass — never a dict of magic string keys. Each validates
its required fields on construction, and exposes ``fields()`` (the API field map, empties omitted) and
``slug_seed()`` (for the Markdown filename). ``DraftRef`` is the backend-agnostic result.
"""

from __future__ import annotations

import dataclasses

import pytest

from chorus_tools.cms import (
    BlogDraft,
    ContentType,
    DraftRef,
    EmailDraft,
    SocialDraft,
    SocialPlatform,
)

pytestmark = pytest.mark.unit


class TestContentType:
    def test_values(self) -> None:
        assert {c.value for c in ContentType} == {"blog", "social", "email"}


class TestBlogDraft:
    def test_valid(self) -> None:
        d = BlogDraft(title="Shipping safely", body="# Body\ntext")
        assert d.content_type is ContentType.BLOG
        assert d.fields() == {"title": "Shipping safely", "body": "# Body\ntext"}
        assert d.slug_seed() == "Shipping safely"

    def test_optional_fields_included_only_when_set(self) -> None:
        d = BlogDraft(title="T", body="B", slug="t", excerpt="hi", seo_description="seo")
        assert d.fields() == {
            "title": "T", "body": "B", "slug": "t", "excerpt": "hi", "seo_description": "seo",
        }

    def test_missing_title_raises(self) -> None:
        with pytest.raises(ValueError, match="title"):
            BlogDraft(title="  ", body="B")

    def test_missing_body_raises(self) -> None:
        with pytest.raises(ValueError, match="body"):
            BlogDraft(title="T", body="")

    def test_frozen(self) -> None:
        d = BlogDraft(title="T", body="B")
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.title = "x"  # type: ignore[misc]


class TestSocialDraft:
    def test_valid(self) -> None:
        d = SocialDraft(platform=SocialPlatform.LINKEDIN, text="A concrete engineering moment.")
        assert d.content_type is ContentType.SOCIAL
        assert d.fields() == {"platform": "linkedin", "text": "A concrete engineering moment."}
        assert d.slug_seed() == "A concrete engineering moment."

    def test_link_included_when_set(self) -> None:
        d = SocialDraft(platform=SocialPlatform.X, text="hey", link="https://arceus.sh")
        assert d.fields() == {"platform": "x", "text": "hey", "link": "https://arceus.sh"}

    def test_empty_text_raises(self) -> None:
        with pytest.raises(ValueError, match="text"):
            SocialDraft(platform=SocialPlatform.LINKEDIN, text="")


class TestEmailDraft:
    def test_valid(self) -> None:
        d = EmailDraft(subject="Welcome", body="body copy")
        assert d.content_type is ContentType.EMAIL
        assert d.fields() == {"subject": "Welcome", "body": "body copy"}
        assert d.slug_seed() == "Welcome"

    def test_optional_included_when_set(self) -> None:
        d = EmailDraft(subject="S", body="B", preheader="pre", segment="founders")
        assert d.fields() == {"subject": "S", "body": "B", "preheader": "pre", "segment": "founders"}

    def test_missing_subject_raises(self) -> None:
        with pytest.raises(ValueError, match="subject"):
            EmailDraft(subject="", body="B")


class TestDraftRef:
    def test_as_dict_roundtrip(self) -> None:
        ref = DraftRef(
            backend="strapi",
            content_type=ContentType.BLOG,
            ref_id="abc123",
            url="http://localhost:1337/admin/...",
        )
        assert ref.status == "draft"
        assert ref.as_dict() == {
            "backend": "strapi",
            "content_type": "blog",
            "ref_id": "abc123",
            "url": "http://localhost:1337/admin/...",
            "status": "draft",
        }
