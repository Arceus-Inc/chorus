"""The dream contract-version guard (spec 05 §2).

chorus binds to **`dream.contracts`** — the cross-repo Protocols — not to dream internals, and pins a
compatible-release requirement on the contract version. :func:`check_dream_contract` is the fail-fast
the composition root runs at import: it asserts the installed dream's ``contracts.__contract_version__``
is within the range chorus was built against and raises a clear :class:`DreamContractError` otherwise,
so a drifted signature is caught at startup rather than mid-beat.
"""

from __future__ import annotations

# The dream contract version chorus is built against. Compatible-release on MAJOR.MINOR: a dream
# whose contract shares this MAJOR and is at least this version is accepted; a MAJOR bump (a breaking
# Protocol change) or an older contract is rejected. Bump this in lockstep with a dream contract bump.
SUPPORTED_DREAM_CONTRACT = "0.1.0"


class DreamContractError(RuntimeError):
    """The installed dream's contract version is missing, malformed, or incompatible (spec 05 §2)."""


def _parse(version: str) -> tuple[int, int, int] | None:
    """Parse ``MAJOR.MINOR.PATCH`` into a comparable tuple, or ``None`` if it is not valid semver."""
    parts = version.split(".")
    if len(parts) != 3:
        return None
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError:
        return None
    if major < 0 or minor < 0 or patch < 0:
        return None
    return (major, minor, patch)


def check_dream_contract(module: object, *, supported: str = SUPPORTED_DREAM_CONTRACT) -> str:
    """Assert the installed dream's contract version is compatible with chorus; return it.

    ``module`` is the imported ``dream`` package. Raises :class:`DreamContractError` when dream does
    not expose ``contracts.__contract_version__`` (a dream predating the seam), the version is not
    valid semver, or it falls outside the compatible-release range (different MAJOR, or older than
    ``supported``). On success returns the version string so the caller can log/record it.
    """
    contracts = getattr(module, "contracts", None)
    version = getattr(contracts, "__contract_version__", None)
    if not isinstance(version, str):
        raise DreamContractError(
            "the installed dream does not expose contracts.__contract_version__ — it predates the "
            "chorus⟂dream contract (spec 05 §2); upgrade dream to a contract-versioned release."
        )
    actual = _parse(version)
    want = _parse(supported)
    if want is None:  # defensive: a misconfigured SUPPORTED_DREAM_CONTRACT is a chorus bug
        raise DreamContractError(
            f"chorus SUPPORTED_DREAM_CONTRACT {supported!r} is not valid semver."
        )
    if actual is None:
        raise DreamContractError(
            f"dream contract version {version!r} is not valid semver (expected MAJOR.MINOR.PATCH)."
        )
    if actual[0] != want[0] or actual < want:
        raise DreamContractError(
            f"dream contract {version} is incompatible with chorus, which was built against "
            f"~= {want[0]}.{want[1]} (>= {supported}, < {want[0] + 1}.0.0). Align the dream pin."
        )
    return version


__all__ = [
    "SUPPORTED_DREAM_CONTRACT",
    "DreamContractError",
    "check_dream_contract",
]
