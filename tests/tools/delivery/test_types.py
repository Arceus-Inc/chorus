"""Delivery types — PublishedRef / DeliveryRecord (design doc: components).

The executor's value objects: what a backend reports after publishing, and the standing delivery
recorded per approval. Frozen, slotted, validating dict round-trips — never a stringly blob.
"""

from __future__ import annotations

import dataclasses

import pytest

from chorus.testing import uid
from chorus_tools._go_live import GoLiveAction
from chorus_tools.delivery import DeliveryError, DeliveryRecord, PublishedRef

pytestmark = pytest.mark.unit


def _ref() -> PublishedRef:
    return PublishedRef(
        backend="strapi",
        ref_id=uid("doc123"),
        url="http://localhost:1337/blog/#/post/doc123",
    )


def _record() -> DeliveryRecord:
    return DeliveryRecord(
        approval_id=uid("apr_1"),
        action=GoLiveAction.PUBLISH,
        target="blog",
        published=_ref(),
    )


class TestPublishedRef:
    def test_frozen(self) -> None:
        ref = _ref()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.url = "x"  # type: ignore[misc]

    def test_rejects_blank_ref_id(self) -> None:
        with pytest.raises(ValueError, match="ref_id"):
            PublishedRef(backend="strapi", ref_id="  ", url="u")

    def test_rejects_blank_backend(self) -> None:
        with pytest.raises(ValueError, match="backend"):
            PublishedRef(backend="", ref_id=uid("doc1"), url="u")


class TestDeliveryRecord:
    def test_frozen(self) -> None:
        record = _record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.target = "x"  # type: ignore[misc]

    def test_dict_round_trip(self) -> None:
        record = _record()
        assert DeliveryRecord.from_dict(record.as_dict()) == record

    def test_as_dict_is_flat_and_json_safe(self) -> None:
        d = _record().as_dict()
        assert d == {
            "approval_id": uid("apr_1"),
            "action": "publish",
            "target": "blog",
            "backend": "strapi",
            "ref_id": uid("doc123"),
            "url": "http://localhost:1337/blog/#/post/doc123",
        }

    def test_from_dict_rejects_missing_field(self) -> None:
        bad = _record().as_dict()
        del bad["ref_id"]
        with pytest.raises(ValueError, match="ref_id"):
            DeliveryRecord.from_dict(bad)

    def test_from_dict_rejects_unknown_action(self) -> None:
        bad = _record().as_dict()
        bad["action"] = "teleport"
        with pytest.raises(ValueError):
            DeliveryRecord.from_dict(bad)

    def test_rejects_blank_approval_id(self) -> None:
        with pytest.raises(ValueError, match="approval_id"):
            DeliveryRecord(
                approval_id="", action=GoLiveAction.PUBLISH, target="blog", published=_ref()
            )


class TestDeliveryError:
    def test_is_a_runtime_error(self) -> None:
        assert issubclass(DeliveryError, RuntimeError)
