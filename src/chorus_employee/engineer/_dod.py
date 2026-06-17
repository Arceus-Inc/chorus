"""The Engineer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

The Engineer's DoD is a **command gate**: the change is done iff the test + lint command
exits zero. The verifier's artifact class is ``pr`` — the Engineer lands a pull request.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_GATE_COMMAND = "pytest -q && ruff check ."


def engineer_dod(intent: str) -> Verifier:
    """The Engineer's DoD generator (spec 04): a CI/test command gate, landing a PR."""
    return Verifier.command(_GATE_COMMAND, artifact_class="pr")


__all__ = ["engineer_dod"]
