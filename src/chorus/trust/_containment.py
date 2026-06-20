"""Runtime containment for a low-trust beat (§4) — the fail-closed conditions (spec 04 §4).

Before a ``low_trust_review`` beat may run, **all** must hold: it runs in an isolated worktree, every
secret it references is in its boundary allow-list, and no secret is passed **inline** (a raw value) —
only approved ``ref:`` handles. Any miss raises :class:`TrustDenied`. A ``standard`` beat needs none of
this (it is trusted) and short-circuits.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from chorus.errors import InvalidIntake
from chorus.roles import Isolation
from chorus.trust._preset import TrustPreset
from chorus.trust._resolver import ResolvedTrust, TrustDenied

_REF_PREFIX = "ref:"
# An env key whose name implies a secret — its value must be an approved ref, never a raw value.
_SECRET_MARKERS: tuple[str, ...] = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "KEY", "CREDENTIAL", "API")


def assert_no_inline_secrets(env: Mapping[str, str] | None) -> None:
    """Raise :class:`InvalidIntake` if any secret-looking key holds a raw value (spec 13 §3).

    The fail-closed half of the trust boundary, pushed to *where env is written* (routine add / revise
    / reconcile / plugin registration) so a plaintext credential can never land in a row. Key-heuristic:
    a key whose name implies a secret must use a ``ref:`` handle; plain non-secret config is untouched.
    The allow-list membership of those refs is checked later, at beat materialize (``assert_contained``).
    """
    for key, value in (env or {}).items():
        if _looks_secret(key) and not value.startswith(_REF_PREFIX):
            raise InvalidIntake(f"inline secret in {key!r} — env must bind a ref: handle, not a value")


def assert_contained(
    resolved: ResolvedTrust, *, isolation: Isolation, env: Iterable[tuple[str, str]]
) -> None:
    """Raise :class:`TrustDenied` unless a low-trust beat meets every containment condition."""
    if resolved.preset is TrustPreset.STANDARD:
        return  # a trusted beat needs no containment
    if isolation is not Isolation.WORKTREE:
        raise TrustDenied("a low-trust beat must run in an isolated worktree")
    allow = resolved.boundary.secret_ref_allowlist if resolved.boundary is not None else frozenset()
    for key, value in env:
        if value.startswith(_REF_PREFIX):
            if value not in allow:
                raise TrustDenied(f"secret ref {value!r} is not in the boundary allow-list")
        elif _looks_secret(key):
            raise TrustDenied(f"inline secret in {key!r} — a low-trust beat must use a ref: handle")


def _looks_secret(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in _SECRET_MARKERS)


__all__ = ["assert_contained", "assert_no_inline_secrets"]
