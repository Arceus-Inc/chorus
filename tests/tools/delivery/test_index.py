"""DeliveryIndex — one delivery per approval, persisted in the worktree (design doc: idempotency)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus_tools._go_live import GoLiveAction
from chorus_tools.delivery import DeliveryRecord, PublishedRef
from chorus_tools.delivery._index import DeliveryIndex

pytestmark = pytest.mark.unit


def _record(approval_id: str = "apr_1", ref_id: str = "doc1") -> DeliveryRecord:
    return DeliveryRecord(
        approval_id=approval_id,
        action=GoLiveAction.PUBLISH,
        target="blog",
        published=PublishedRef(backend="strapi", ref_id=ref_id, url=f"u://{ref_id}"),
    )


class TestDeliveryIndex:
    def test_missing_approval_returns_none(self, tmp_path: Path) -> None:
        index = DeliveryIndex(tmp_path / ".harness" / "deliveries.json")
        assert index.standing_delivery("apr_1") is None

    def test_record_then_read(self, tmp_path: Path) -> None:
        index = DeliveryIndex(tmp_path / ".harness" / "deliveries.json")
        index.record(_record())
        assert index.standing_delivery("apr_1") == _record()

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / ".harness" / "deliveries.json"
        DeliveryIndex(path).record(_record())
        assert DeliveryIndex(path).standing_delivery("apr_1") == _record()

    def test_distinct_approvals_are_independent(self, tmp_path: Path) -> None:
        index = DeliveryIndex(tmp_path / "d.json")
        index.record(_record("apr_1", "doc1"))
        index.record(_record("apr_2", "doc2"))
        assert index.standing_delivery("apr_1") == _record("apr_1", "doc1")
        assert index.standing_delivery("apr_2") == _record("apr_2", "doc2")

    def test_malformed_file_degrades_to_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "d.json"
        path.write_text("not json", encoding="utf-8")
        assert DeliveryIndex(path).standing_delivery("apr_1") is None
