"""Cron / routines (spec 03 §4) — a firing writes a task, never runs an agent.

The routine data model + enums are the canonical ledger model (:mod:`chorus.ledger`); the firing
engine is :func:`chorus.cron._fire.fire_routine`. This package's public surface is the cron parser.
"""

from __future__ import annotations

from chorus.cron._routine import parse_cron

__all__ = ["parse_cron"]
