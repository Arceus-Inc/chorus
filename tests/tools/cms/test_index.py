"""CmsDraftIndex + DraftRef.from_dict — the standing-draft bookkeeping (design: idempotency).

The index maps an idempotency key -> the DraftRef last staged for it, persisted in the worktree so a
re-called cms_draft within the same task updates the standing draft instead of duplicating it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus_tools.cms import ContentType, DraftRef
from chorus_tools.cms._index import CmsDraftIndex

pytestmark = pytest.mark.unit


def _ref(ref_id: str = "doc1") -> DraftRef:
    return DraftRef(backend="strapi", content_type=ContentType.BLOG, ref_id=ref_id, url="u://1")


class TestDraftRefRoundTrip:
    def test_from_dict_inverts_as_dict(self) -> None:
        ref = _ref()
        assert DraftRef.from_dict(ref.as_dict()) == ref


class TestCmsDraftIndex:
    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        index = CmsDraftIndex(tmp_path / ".harness" / "cms-drafts.json")
        assert index.standing_ref("blog:t1") is None

    def test_record_then_read(self, tmp_path: Path) -> None:
        index = CmsDraftIndex(tmp_path / ".harness" / "cms-drafts.json")
        index.record("blog:t1", _ref("doc1"))
        assert index.standing_ref("blog:t1") == _ref("doc1")

    def test_record_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / ".harness" / "cms-drafts.json"
        CmsDraftIndex(path).record("blog:t1", _ref("doc1"))
        assert CmsDraftIndex(path).standing_ref("blog:t1") == _ref("doc1")

    def test_distinct_keys_are_independent(self, tmp_path: Path) -> None:
        index = CmsDraftIndex(tmp_path / ".harness" / "cms-drafts.json")
        index.record("blog:t1", _ref("b1"))
        index.record("social:t1", _ref("s1"))
        assert index.standing_ref("blog:t1") == _ref("b1")
        assert index.standing_ref("social:t1") == _ref("s1")

    def test_record_overwrites_same_key(self, tmp_path: Path) -> None:
        index = CmsDraftIndex(tmp_path / ".harness" / "cms-drafts.json")
        index.record("blog:t1", _ref("old"))
        index.record("blog:t1", _ref("new"))
        assert index.standing_ref("blog:t1") == _ref("new")
