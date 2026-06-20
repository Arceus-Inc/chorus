"""Experiments — runnable harnesses and tooling that live *outside* the shipped SDK.

Nothing under ``src/`` imports from here. These are operator-facing scripts: long-run drivers and the
:mod:`experiments.insights` observability platform you point at a finished (or in-flight) run's ledger.
"""

from __future__ import annotations
