"""Token pricing — dream's per-model usage totalled into whole cents (spec 04 §3)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from chorus.adapters import ModelRate, TokenPricing

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Usage:
    """A stand-in for dream's ``UsageSnapshot`` — only the token counts the pricer reads."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def test_prices_input_and_output_per_million() -> None:
    pricing = TokenPricing(rates={"gpt-x": ModelRate(125, 1000)})
    cost = pricing.cost_cents({"gpt-x": _Usage(input_tokens=1_000_000, output_tokens=1_000_000)})
    assert cost == 1125  # 125 (input) + 1000 (output)


def test_sums_across_models() -> None:
    pricing = TokenPricing(rates={"a": ModelRate(100, 100), "b": ModelRate(200, 200)})
    cost = pricing.cost_cents(
        {"a": _Usage(input_tokens=1_000_000), "b": _Usage(output_tokens=1_000_000)}
    )
    assert cost == 300


def test_unknown_model_uses_the_default_rate() -> None:
    pricing = TokenPricing(rates={}, default=ModelRate(500, 500))
    assert pricing.cost_cents({"mystery": _Usage(input_tokens=1_000_000)}) == 500


def test_unknown_model_without_a_default_contributes_zero() -> None:
    pricing = TokenPricing(rates={})  # no rate, no default
    assert (
        pricing.cost_cents({"mystery": _Usage(input_tokens=1_000_000, output_tokens=1_000_000)})
        == 0
    )


def test_empty_usage_is_zero() -> None:
    assert TokenPricing(rates={"a": ModelRate(100, 100)}).cost_cents({}) == 0


def test_rounds_half_up_to_whole_cents() -> None:
    # 4000 input tokens * 125 cents/Mtok = 0.5 cent -> rounds to 1
    pricing = TokenPricing(rates={"a": ModelRate(125, 0)})
    assert pricing.cost_cents({"a": _Usage(input_tokens=4000)}) == 1


def test_sub_half_cent_rounds_down() -> None:
    pricing = TokenPricing(rates={"a": ModelRate(125, 0)})
    assert pricing.cost_cents({"a": _Usage(input_tokens=1)}) == 0


def test_cache_tokens_are_priced_when_a_rate_is_set() -> None:
    rate = ModelRate(0, 0, cache_read_cents_per_mtok=10, cache_write_cents_per_mtok=20)
    pricing = TokenPricing(rates={"a": rate})
    usage = _Usage(cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
    assert pricing.cost_cents({"a": usage}) == 30


def test_rate_for_resolves_known_then_default() -> None:
    pricing = TokenPricing(rates={"a": ModelRate(1, 2)}, default=ModelRate(9, 9))
    assert pricing.rate_for("a") == ModelRate(1, 2)
    assert pricing.rate_for("z") == ModelRate(9, 9)
    assert TokenPricing(rates={}).rate_for("z") is None
