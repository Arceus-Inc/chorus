"""Cross-child coherence — the AGENTS.md contract + the deterministic reconciliation checker (spec 15).

The manager authors ``AGENTS.md`` (module map · public API · ownership) at decompose; the checker
reconciles the merged tree to it at the integrate beat so a ``--org`` build lands a single coherent
public surface or ends ``blocked`` with a specific coherence reason — never a silent split-brain done.
"""

from __future__ import annotations

from chorus.coherence._agents_md import AgentsMd
from chorus.coherence._checker import (
    CoherenceViolation,
    authored_contract,
    check_coherence,
    contract_sha,
    is_placeholder,
)

__all__ = [
    "AgentsMd",
    "CoherenceViolation",
    "authored_contract",
    "check_coherence",
    "contract_sha",
    "is_placeholder",
]
