"""The dream contract-version guard — fail fast on a drifted seam (spec 05 §2).

``check_dream_contract`` is the import-time assertion the composition root runs: the installed dream's
``contracts.__contract_version__`` must be a compatible release of what chorus was built against. These
tests stand a fake ``dream`` module (a namespace with a ``contracts`` attribute) in for the real SDK.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from chorus.adapters import SUPPORTED_DREAM_CONTRACT, DreamContractError, check_dream_contract

pytestmark = pytest.mark.unit


def _dream(version: object) -> SimpleNamespace:
    """A stand-in ``dream`` module exposing ``contracts.__contract_version__ = version``."""
    return SimpleNamespace(contracts=SimpleNamespace(__contract_version__=version))


def test_accepts_the_exact_supported_version() -> None:
    assert check_dream_contract(_dream(SUPPORTED_DREAM_CONTRACT)) == SUPPORTED_DREAM_CONTRACT


def test_accepts_a_forward_compatible_minor() -> None:
    # same MAJOR, newer MINOR — a non-breaking contract addition is compatible.
    assert check_dream_contract(_dream("0.4.0"), supported="0.1.0") == "0.4.0"


def test_accepts_a_forward_compatible_patch() -> None:
    assert check_dream_contract(_dream("0.1.7"), supported="0.1.0") == "0.1.7"


def test_rejects_a_major_bump() -> None:
    with pytest.raises(DreamContractError, match="incompatible"):
        check_dream_contract(_dream("1.0.0"), supported="0.1.0")


def test_rejects_an_older_contract() -> None:
    with pytest.raises(DreamContractError, match="incompatible"):
        check_dream_contract(_dream("0.1.0"), supported="0.2.0")


def test_rejects_a_missing_contract_version() -> None:
    # a dream predating the seam exposes no contracts.__contract_version__.
    with pytest.raises(DreamContractError, match="predates"):
        check_dream_contract(SimpleNamespace())


def test_rejects_a_non_string_contract_version() -> None:
    with pytest.raises(DreamContractError, match="predates"):
        check_dream_contract(_dream(0.1))


def test_rejects_a_non_semver_string() -> None:
    with pytest.raises(DreamContractError, match="not valid semver"):
        check_dream_contract(_dream("0.1"), supported="0.1.0")
