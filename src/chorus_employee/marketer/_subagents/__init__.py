"""Marketer subagents — the Strategist, Brand-Critic, and Creative/Copywriter (design doc §06, §10).

Three Tier-1, role-owned specialists Mira spawns mid-beat:

- **Strategist** — frames the grounded bet *before* drafting: a web-research-grounded hypothesis
  and channel plan the Creative can draft straight from. Depth-2 (spawns web_research). See
  ``_strategist``.
- **Brand-Critic** — an adversarial reviewer that checks her drafted content against the voice
  spec. Read-only (never edits), so Mira keeps ownership of revisions. This is the "post-gen"
  layer of the validation sandwich (§10): an agentic adversary that reasons about brand fidelity.
  See ``_brand_critic``.
- **Creative/Copywriter** — a *variation engine*. Given a research-grounded seed Mira writes, it
  drafts a handful of on-brand variants (§10 variety) to the worktree, self-lints each, and returns
  a typed manifest. It varies *expression*, never *evidence* — the seed's cited claims are
  preserved verbatim, so it cannot fabricate a metric. It writes but never publishes or selects;
  Mira prunes among {seed + variants} and promotes the winner. See ``_creative``.

Tier-1, role-owned. Each spec's ``tools`` are CHORUS names (mapped to dream + intersected with the
marketer's toolset at materialize). Each spawned child's system prompt is generated from name +
description, so the full brief lives *in* the description — imperative, so the specialist actually
reads the files and produces its deliverable rather than claiming it cannot.
"""

from __future__ import annotations

from chorus_employee.marketer._subagents._brand_critic import BRAND_CRITIC_SUBAGENT
from chorus_employee.marketer._subagents._creative import CREATIVE_SUBAGENT
from chorus_employee.marketer._subagents._strategist import STRATEGIST_SUBAGENT

__all__ = ["BRAND_CRITIC_SUBAGENT", "CREATIVE_SUBAGENT", "STRATEGIST_SUBAGENT"]
