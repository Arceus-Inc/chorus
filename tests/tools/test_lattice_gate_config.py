"""The lattice consolidation gate is operator-tunable via env (F4 warm-start)."""

from __future__ import annotations

import pytest

from chorus_tools._lattice_bridge import build_lattice_for_chorus

pytestmark = pytest.mark.unit


def test_gate_thresholds_default_to_lattice_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CHORUS_LATTICE_MIN_CLUSTER", raising=False)
    monkeypatch.delenv("CHORUS_LATTICE_MIN_NEW", raising=False)
    lat = build_lattice_for_chorus(tmp_path)
    assert lat._min_cluster == 2  # repetition-based default


def test_env_warm_starts_the_gate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHORUS_LATTICE_MIN_CLUSTER", "1")
    monkeypatch.setenv("CHORUS_LATTICE_MIN_NEW", "1")
    lat = build_lattice_for_chorus(tmp_path)
    assert lat._min_cluster == 1  # consolidate from a single strong episode early in company life
    assert lat._min_new == 1


def test_explicit_argument_wins_over_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHORUS_LATTICE_MIN_CLUSTER", "1")
    lat = build_lattice_for_chorus(tmp_path, min_cluster_size=3)
    assert lat._min_cluster == 3


def test_malformed_env_falls_back_to_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHORUS_LATTICE_MIN_CLUSTER", "not-an-int")
    lat = build_lattice_for_chorus(tmp_path)
    assert lat._min_cluster == 2
