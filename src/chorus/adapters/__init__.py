"""Adapters — the wiring boundary to external runtimes (spec 05, spec 10 §1).

Modules here adapt an external SDK to a chorus contract. They are the seam the composition root wires;
keeping them in one package makes the boundary explicit. :class:`DreamBeatRunner` runs a beat through
the dream Harness behind the :class:`~chorus.heartbeat.BeatRunner` protocol.
"""

from __future__ import annotations

from chorus.adapters._capacity import CapacityAdapter
from chorus.adapters._contract import (
    SUPPORTED_DREAM_CONTRACT,
    DreamContractError,
    check_dream_contract,
)
from chorus.adapters._delegated_intake import DelegatedIntakeAdapter
from chorus.adapters._observer import DreamObserverBridge
from chorus.adapters._pricing import (
    ModelRate,
    TokenPricing,
    UsageView,
    default_token_pricing,
    pricing_from_env_if_configured,
)
from chorus.adapters.dream_beat import (
    DreamBeatRunner,
    DreamStepStatus,
    RunResult,
    TaskHarness,
    to_beat_outcome,
)

__all__ = [
    "SUPPORTED_DREAM_CONTRACT",
    "CapacityAdapter",
    "DelegatedIntakeAdapter",
    "DreamBeatRunner",
    "DreamContractError",
    "DreamObserverBridge",
    "DreamStepStatus",
    "ModelRate",
    "RunResult",
    "TaskHarness",
    "TokenPricing",
    "UsageView",
    "check_dream_contract",
    "default_token_pricing",
    "pricing_from_env_if_configured",
    "to_beat_outcome",
]
