"""WebPlugin trust binding — capability classes, spend caps, and the secret-ref boundary (spec GM §5).

A web plugin is external reach, and reach is graded by *blast radius*. This module is the
role-agnostic trust vocabulary the registry validates against, reusing the two ideas chorus already
ships rather than inventing new governance:

- **secret-ref binding** — auth is an env handle (``ref:…``), never an inline value. The same
  fail-closed boundary as :func:`chorus.trust.assert_no_inline_secrets`, applied to a plugin's auth.
- **graded capability** — ``READ``/``WRITE_DESIGN`` are cheap and reversible (ungated); ``SEND`` and
  ``SPEND`` reach real users or money and are **gated** — they require a :class:`SpendCap` so a
  runaway plugin trips the same budget circuit-breaker as a runaway model run (spec 04 §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Auth is a reference to a secret, never the secret itself (reused from spec 13's env boundary).
REF_PREFIX = "ref:"


class PluginKind(StrEnum):
    """The category of external system a plugin reaches — vendor-agnostic (spec GM §5)."""

    WAREHOUSE = "warehouse"  # Snowflake / BigQuery — analytic store
    ANALYTICS = "analytics"  # Amplitude / GA4 / Mixpanel — event & funnel API
    EXPERIMENTATION = "experimentation"  # Statsig / Optimizely — test design + results
    EMAIL_CRM = "email_crm"  # Braze / Customer.io / Klaviyo — audience send
    ADS = "ads"  # Meta / Google Ads — paid acquisition
    CREATIVE_DAM = "creative_dam"  # Figma / brand DAM — creative assets
    SOCIAL = "social"  # Twitter/X / LinkedIn — organic post publishing
    SEARCH = "search"  # Google / LinkedIn / X search — read-only lead discovery
    OUTREACH = "outreach"  # cold DM / connection request — 1:1 lead contact (gated)


class Capability(StrEnum):
    """What a plugin may *do*, ordered by blast radius (spec GM §5, §9).

    ``READ`` and ``WRITE_DESIGN`` are autonomous (reversible, no live effect); ``SEND`` and
    ``SPEND`` cross the human gate because they reach real users or spend money.
    """

    READ = "read"  # ungated, cheap, reversible
    WRITE_DESIGN = "write_design"  # creates drafts only — no live effect
    SEND = "send"  # reaches real users → gated
    SPEND = "spend"  # spends money → gated + budget cap

    @property
    def gated(self) -> bool:
        """True iff exercising this capability crosses the human-approval gate (spec GM §9)."""
        return self in (Capability.SEND, Capability.SPEND)


@dataclass(frozen=True)
class SpendCap:
    """A fail-closed budget ceiling for a gated plugin (spec GM §5, §9 gate 2).

    Both limits are upper bounds in cents; ``None`` means "not separately capped". A gated plugin
    must carry a cap (enforced at registration) so a spend/send can never be unbounded — the cap is
    the chorus budget gate-2 surface expressed at the integration boundary, not new machinery.
    """

    per_action_cents: int | None = None
    daily_cents: int | None = None

    def __post_init__(self) -> None:
        for label, value in (("per_action_cents", self.per_action_cents), ("daily_cents", self.daily_cents)):
            if value is not None and value < 0:
                raise ValueError(f"{label} must be non-negative, got {value}")

    def allows(self, *, action_cents: int) -> bool:
        """Whether a single action of ``action_cents`` is within the per-action ceiling."""
        return self.per_action_cents is None or action_cents <= self.per_action_cents

    @property
    def bounded(self) -> bool:
        """True iff this cap actually constrains spend — at least one ceiling is set.

        An all-``None`` ``SpendCap`` is structurally present but enforces nothing, so the registry
        treats it as *uncapped* (a gated plugin needs a real bound, not a hollow one).
        """
        return self.per_action_cents is not None or self.daily_cents is not None


@dataclass(frozen=True)
class RateCap:
    """A fail-closed *volume* ceiling for a gated SEND plugin (spec GM §5; Result/Polsia channel limits).

    Spend isn't the only blast radius — an organic channel (Twitter/X 1 post/day, an email list
    2 sends/day) is capped by *frequency*, not dollars. ``per_day`` is the max number of sends in a
    rolling day; ``None`` means "not separately capped". The send loop checks :meth:`allows` against
    how many sends already went out today, so a runaway agent can't spam a channel.
    """

    per_day: int | None = None

    def __post_init__(self) -> None:
        if self.per_day is not None and self.per_day < 0:
            raise ValueError(f"per_day must be non-negative, got {self.per_day}")

    def allows(self, *, sent_today: int) -> bool:
        """Whether one more send is within today's frequency ceiling."""
        return self.per_day is None or sent_today < self.per_day

    @property
    def bounded(self) -> bool:
        """True iff this cap actually constrains volume — a per-day ceiling is set."""
        return self.per_day is not None


def is_secret_ref(value: str) -> bool:
    """True iff ``value`` is a secret *reference* (``ref:…``) rather than a raw inline value."""
    return value.startswith(REF_PREFIX) and len(value) > len(REF_PREFIX)


__all__ = [
    "REF_PREFIX",
    "Capability",
    "PluginKind",
    "RateCap",
    "SpendCap",
    "is_secret_ref",
]
