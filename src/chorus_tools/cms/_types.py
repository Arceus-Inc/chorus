"""The `cms.draft` domain types — one typed value per channel (design doc: content model).

Each channel is its own frozen dataclass with the fields that channel actually has — never a bag of
magic string keys. Every draft validates its required fields on construction and exposes a uniform
:class:`CmsDraft` shape (``content_type`` + ``fields()`` + ``slug_seed()``) so a backend can render it
without knowing the concrete type. :class:`DraftRef` is the backend-agnostic result of a create.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from chorus_tools._validate import require as _require


class ContentType(StrEnum):
    """The channel a draft targets — the discriminator that routes it to a collection."""

    BLOG = "blog"
    SOCIAL = "social"
    EMAIL = "email"


class SocialPlatform(StrEnum):
    """The social network a :class:`SocialDraft` is written for."""

    LINKEDIN = "linkedin"
    X = "x"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class CmsError(RuntimeError):
    """A CMS backend failed to create a draft (network, auth, or a rejected payload)."""


@runtime_checkable
class CmsDraft(Protocol):
    """The uniform shape a backend renders — implemented by each per-channel draft type."""

    @property
    def content_type(self) -> ContentType: ...

    def fields(self) -> dict[str, str]:
        """The API field map for this draft — required fields plus any set optionals, empties omitted."""
        ...

    def slug_seed(self) -> str:
        """The human text a Markdown backend slugifies into a filename."""
        ...


@dataclass(frozen=True, slots=True)
class BlogDraft:
    """Long-form blog content (`content_type=blog`)."""

    title: str
    body: str
    slug: str = ""
    excerpt: str = ""
    seo_description: str = ""

    def __post_init__(self) -> None:
        _require(self.title, "title")
        _require(self.body, "body")

    @property
    def content_type(self) -> ContentType:
        return ContentType.BLOG

    def fields(self) -> dict[str, str]:
        out = {"title": self.title, "body": self.body}
        _put(out, "slug", self.slug)
        _put(out, "excerpt", self.excerpt)
        _put(out, "seo_description", self.seo_description)
        return out

    def slug_seed(self) -> str:
        return self.title


@dataclass(frozen=True, slots=True)
class SocialDraft:
    """Short-form social content (`content_type=social`) — the text *is* the content, no title."""

    platform: SocialPlatform
    text: str
    link: str = ""
    scheduled_at: str = ""

    def __post_init__(self) -> None:
        _require(self.text, "text")

    @property
    def content_type(self) -> ContentType:
        return ContentType.SOCIAL

    def fields(self) -> dict[str, str]:
        out = {"platform": self.platform.value, "text": self.text}
        _put(out, "link", self.link)
        _put(out, "scheduled_at", self.scheduled_at)
        return out

    def slug_seed(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class EmailDraft:
    """Email / lifecycle content (`content_type=email`)."""

    subject: str
    body: str
    preheader: str = ""
    segment: str = ""

    def __post_init__(self) -> None:
        _require(self.subject, "subject")
        _require(self.body, "body")

    @property
    def content_type(self) -> ContentType:
        return ContentType.EMAIL

    def fields(self) -> dict[str, str]:
        out = {"subject": self.subject, "body": self.body}
        _put(out, "preheader", self.preheader)
        _put(out, "segment", self.segment)
        return out

    def slug_seed(self) -> str:
        return self.subject


@dataclass(frozen=True, slots=True)
class DraftRef:
    """The result of a successful draft create — where the draft lives, reversibly."""

    backend: str  # "markdown" | "strapi"
    content_type: ContentType
    ref_id: str  # markdown: relative path · strapi: documentId
    url: str  # a human-openable pointer
    status: str = "draft"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> DraftRef:
        """Inverse of :meth:`as_dict` — rehydrate a ref persisted in the standing-draft index."""
        return cls(
            backend=data["backend"],
            content_type=ContentType(data["content_type"]),
            ref_id=data["ref_id"],
            url=data["url"],
            status=data.get("status", "draft"),
        )


def draft_from_fields(content_type: ContentType, fields: dict[str, object]) -> CmsDraft:
    """Rebuild a typed draft from a backend's stored field map — the inverse of ``draft.fields()``.

    The read half of ``read_draft``: a missing/blank required field or an unknown enum value raises
    :class:`CmsError` naming the field, so a corrupted store can never yield a half-valid draft.
    """
    try:
        if content_type is ContentType.BLOG:
            return BlogDraft(
                title=_text(fields, "title"),
                body=_text(fields, "body"),
                slug=_text(fields, "slug", optional=True),
                excerpt=_text(fields, "excerpt", optional=True),
                seo_description=_text(fields, "seo_description", optional=True),
            )
        if content_type is ContentType.SOCIAL:
            return SocialDraft(
                platform=SocialPlatform(_text(fields, "platform")),
                text=_text(fields, "text"),
                link=_text(fields, "link", optional=True),
                scheduled_at=_text(fields, "scheduled_at", optional=True),
            )
        return EmailDraft(
            subject=_text(fields, "subject"),
            body=_text(fields, "body"),
            preheader=_text(fields, "preheader", optional=True),
            segment=_text(fields, "segment", optional=True),
        )
    except ValueError as exc:
        raise CmsError(f"stored {content_type.value} draft is invalid: {exc}") from exc


def _text(fields: dict[str, object], key: str, *, optional: bool = False) -> str:
    """A string field from a stored map; blank/absent is '' when optional, else a named error."""
    value = fields.get(key)
    if isinstance(value, str) and value.strip():
        return value
    if optional:
        return ""
    raise ValueError(f"{key} is missing")


def _put(target: dict[str, str], key: str, value: str) -> None:
    """Add ``key`` to ``target`` only when ``value`` is non-blank (optional fields stay absent)."""
    if value and value.strip():
        target[key] = value


__all__ = [
    "BlogDraft",
    "CmsDraft",
    "CmsError",
    "ContentType",
    "DraftRef",
    "EmailDraft",
    "SocialDraft",
    "SocialPlatform",
    "draft_from_fields",
]
