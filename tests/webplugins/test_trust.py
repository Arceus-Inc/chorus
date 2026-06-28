"""WebPlugin trust vocabulary — graded capability, spend caps, secret-ref binding (spec GM §5)."""

from __future__ import annotations

import pytest

from chorus.webplugins import Capability, RateCap, SpendCap, is_secret_ref

pytestmark = pytest.mark.unit


def test_read_and_design_are_ungated_send_and_spend_are_gated() -> None:
    assert Capability.READ.gated is False
    assert Capability.WRITE_DESIGN.gated is False
    assert Capability.SEND.gated is True
    assert Capability.SPEND.gated is True


def test_is_secret_ref_accepts_handles_and_rejects_inline_values() -> None:
    assert is_secret_ref("ref:warehouse_ro") is True
    assert is_secret_ref("ref:") is False  # an empty handle is not a real ref
    assert is_secret_ref("sk-live-123") is False
    assert is_secret_ref("") is False


def test_spend_cap_allows_within_per_action_ceiling() -> None:
    cap = SpendCap(per_action_cents=500_00)
    assert cap.allows(action_cents=400_00) is True
    assert cap.allows(action_cents=500_00) is True
    assert cap.allows(action_cents=600_00) is False


def test_spend_cap_with_no_per_action_limit_allows_anything() -> None:
    assert SpendCap().allows(action_cents=10_000_00) is True


def test_spend_cap_rejects_negative_limits() -> None:
    with pytest.raises(ValueError):
        SpendCap(per_action_cents=-1)
    with pytest.raises(ValueError):
        SpendCap(daily_cents=-5)


def test_rate_cap_allows_until_the_daily_count_is_hit() -> None:
    cap = RateCap(per_day=2)
    assert cap.allows(sent_today=0) is True
    assert cap.allows(sent_today=1) is True
    assert cap.allows(sent_today=2) is False  # the third send would exceed 2/day


def test_rate_cap_with_no_per_day_limit_allows_anything() -> None:
    assert RateCap().allows(sent_today=10_000) is True


def test_rate_cap_rejects_negative_limits() -> None:
    with pytest.raises(ValueError):
        RateCap(per_day=-1)


def test_bounded_reflects_whether_a_cap_actually_constrains() -> None:
    assert SpendCap(per_action_cents=None, daily_cents=None).bounded is False  # hollow
    assert SpendCap(daily_cents=100).bounded is True
    assert SpendCap(per_action_cents=100).bounded is True
    assert RateCap().bounded is False
    assert RateCap(per_day=1).bounded is True
