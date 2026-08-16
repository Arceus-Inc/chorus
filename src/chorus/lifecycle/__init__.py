"""Task lifecycle rules (spec 02) — the status machine, liveness, and recovery glue.

Internal package: the rules the ledger/scheduler enforce on a task as it moves
through its lifecycle. Nothing here is part of chorus's public API (``chorus``);
the facade and repos consume it.
"""

from __future__ import annotations

from chorus.lifecycle._audit import record_activity
from chorus.lifecycle._authority import (
    AuthorityIntersection,
    AuthorityLimits,
    AuthorizationResult,
    EffectiveAuthority,
)
from chorus.lifecycle._capability import (
    CapabilityService,
    ChildPlan,
    ClaimDraft,
    DecisionOutcome,
    DecomposeResult,
    OutcomeMismatch,
)
from chorus.lifecycle._coordination import assign_task, deliver_message
from chorus.lifecycle._decompose import (
    DEFAULT_REQUEST_DEPTH_CAP,
    ChildSpec,
    DepthCapped,
    Fanned,
    decompose,
)
from chorus.lifecycle._delegation_resolution import (
    DelegationResolutionError,
    DelegationResolutionPolicy,
)
from chorus.lifecycle._disposition import (
    Disposition,
    DispositionAction,
    reconcile_disposition,
)
from chorus.lifecycle._lead_selector import LeadSelector
from chorus.lifecycle._liveness import Health, Liveness, classify
from chorus.lifecycle._revise_dod import (
    NoRevision,
    ReviseOutcome,
    RevisionAuthorityError,
    revise_dod,
)
from chorus.lifecycle._team_policy import MissionTeamPolicy, MissionTeamPolicyDenied
from chorus.lifecycle._transitions import (
    LEGAL_TRANSITIONS,
    TERMINAL,
    IllegalTransition,
    assert_legal,
    entry_stamp,
    is_legal,
)

__all__ = [
    "DEFAULT_REQUEST_DEPTH_CAP",
    "LEGAL_TRANSITIONS",
    "TERMINAL",
    "AuthorityIntersection",
    "AuthorityLimits",
    "AuthorizationResult",
    "CapabilityService",
    "ChildPlan",
    "ChildSpec",
    "ClaimDraft",
    "DecisionOutcome",
    "DecomposeResult",
    "DelegationResolutionError",
    "DelegationResolutionPolicy",
    "DepthCapped",
    "Disposition",
    "DispositionAction",
    "EffectiveAuthority",
    "Fanned",
    "Health",
    "IllegalTransition",
    "LeadSelector",
    "Liveness",
    "MissionTeamPolicy",
    "MissionTeamPolicyDenied",
    "NoRevision",
    "OutcomeMismatch",
    "ReviseOutcome",
    "RevisionAuthorityError",
    "assert_legal",
    "assign_task",
    "classify",
    "decompose",
    "deliver_message",
    "entry_stamp",
    "is_legal",
    "reconcile_disposition",
    "record_activity",
    "revise_dod",
]
