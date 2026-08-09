"""Token pricing — turn dream's per-model usage into a cost in cents (spec 04 §3).

dream counts tokens but deliberately does not price them (its own note defers pricing to "a later
layer" — this one). A :class:`TokenPricing` maps each model to a :class:`ModelRate` (whole cents per
million tokens, the unit vendor sheets quote) and totals the usage dream reports on a run. It is a
small, pure value object: the dream adapter may be priced or not (``None`` → unpriced, cost 0), and a
missing rate never raises — so a pricing gap can't crash a beat or silently block it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_DEFAULT_INPUT_CENTS_PER_MTOK = 125
_DEFAULT_OUTPUT_CENTS_PER_MTOK = 1000

_PER_MILLION = 1_000_000


@runtime_checkable
class UsageView(Protocol):
    """The per-model token counts read off dream's ``RunTaskResult.usage_by_model``.

    Structural, so the adapter never imports dream's ``UsageSnapshot`` — anything exposing these four
    counts prices the same way.
    """

    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...

    @property
    def cache_read_tokens(self) -> int: ...

    @property
    def cache_write_tokens(self) -> int: ...


@dataclass(frozen=True)
class ModelRate:
    """Price for one model, in whole cents per million tokens. Cache rates default to 0."""

    input_cents_per_mtok: int
    output_cents_per_mtok: int
    cache_read_cents_per_mtok: int = 0
    cache_write_cents_per_mtok: int = 0

    def cost_micro_cents(self, usage: UsageView) -> int:
        """This rate applied to ``usage`` in micro-cents (cents * 1e6) — deferred division stays exact."""
        return (
            usage.input_tokens * self.input_cents_per_mtok
            + usage.output_tokens * self.output_cents_per_mtok
            + usage.cache_read_tokens * self.cache_read_cents_per_mtok
            + usage.cache_write_tokens * self.cache_write_cents_per_mtok
        )


@dataclass(frozen=True)
class TokenPricing:
    """A model → rate table that totals a run's per-model usage into whole cents.

    A model absent from ``rates`` falls back to ``default``; with no default its usage is unpriced
    (contributes 0) rather than raising.
    """

    rates: Mapping[str, ModelRate]
    default: ModelRate | None = None

    def rate_for(self, model: str) -> ModelRate | None:
        """The rate for ``model`` — its own, else the default, else ``None``."""
        return self.rates.get(model, self.default)

    def cost_cents(self, usage_by_model: Mapping[str, UsageView]) -> int:
        """Total ``usage_by_model`` to whole cents, rounding half up."""
        micro = 0
        for model, usage in usage_by_model.items():
            rate = self.rate_for(model)
            if rate is not None:
                micro += rate.cost_micro_cents(usage)
        return (micro + _PER_MILLION // 2) // _PER_MILLION


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def pricing_from_env_if_configured() -> TokenPricing | None:
    """Return a pricing table only when the operator configured rates via env.

    Without explicit configuration the beat is **unpriced** (tokens metered, cost 0)
    so illustrative defaults never become authoritative ledger spend.
    """
    rates_raw = os.environ.get("CHORUS_PRICE_RATES")
    if rates_raw:
        try:
            import json

            parsed = json.loads(rates_raw)
            if isinstance(parsed, dict) and parsed:
                rates = {
                    str(model): ModelRate(
                        input_cents_per_mtok=int(entry.get("input", _DEFAULT_INPUT_CENTS_PER_MTOK)),
                        output_cents_per_mtok=int(
                            entry.get("output", _DEFAULT_OUTPUT_CENTS_PER_MTOK)
                        ),
                        cache_read_cents_per_mtok=int(entry.get("cache_read", 0)),
                        cache_write_cents_per_mtok=int(entry.get("cache_write", 0)),
                    )
                    for model, entry in parsed.items()
                    if isinstance(entry, dict)
                }
                if rates:
                    return TokenPricing(rates=rates)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    if os.environ.get("CHORUS_PRICE_INPUT_CENTS_PER_MTOK") is not None or os.environ.get(
        "CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK"
    ) is not None:
        default_rate = ModelRate(
            input_cents_per_mtok=_env_int(
                "CHORUS_PRICE_INPUT_CENTS_PER_MTOK", _DEFAULT_INPUT_CENTS_PER_MTOK
            ),
            output_cents_per_mtok=_env_int(
                "CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK", _DEFAULT_OUTPUT_CENTS_PER_MTOK
            ),
            cache_read_cents_per_mtok=_env_int("CHORUS_PRICE_CACHE_READ_CENTS_PER_MTOK", 0),
            cache_write_cents_per_mtok=_env_int("CHORUS_PRICE_CACHE_WRITE_CENTS_PER_MTOK", 0),
        )
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
        rates = {deployment: default_rate} if deployment else {}
        return TokenPricing(rates=rates, default=default_rate)
    return None


def default_token_pricing() -> TokenPricing:
    """Explicit illustrative pricing for demos — never applied implicitly by the factory."""
    default_rate = ModelRate(
        input_cents_per_mtok=_env_int("CHORUS_INPUT_CENTS_PER_MTOK", _DEFAULT_INPUT_CENTS_PER_MTOK),
        output_cents_per_mtok=_env_int(
            "CHORUS_OUTPUT_CENTS_PER_MTOK", _DEFAULT_OUTPUT_CENTS_PER_MTOK
        ),
    )
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
    rates = {deployment: default_rate} if deployment else {}
    return TokenPricing(rates=rates, default=default_rate)


__all__ = [
    "ModelRate",
    "TokenPricing",
    "UsageView",
    "default_token_pricing",
    "pricing_from_env_if_configured",
]
