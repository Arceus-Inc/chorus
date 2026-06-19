"""apply_trust (§4) — the per-beat narrowing the factory applies at materialize.

Resolves the task's effective trust over the role config, asserts containment, and clamps the config's
sandbox / permission_mode (a low-trust beat → read-only / plan). A denied beat raises (not materialized).
"""

from __future__ import annotations

import pytest

from chorus.ledger import OriginKind, Task, TaskStatus
from chorus.roles import RoleBeatConfig
from chorus.trust import TrustDenied, TrustPolicy, TrustPreset
from chorus_harness import apply_trust

pytestmark = pytest.mark.unit


def _config(**over: object) -> RoleBeatConfig:
    base = {"system_prompt": "you are an engineer", "sandbox": "unrestricted",
            "permission_mode": "default", "isolation": "worktree"}
    base.update(over)
    return RoleBeatConfig(**base)  # type: ignore[arg-type]


def _task(**over: object) -> Task:
    base = {"id": "t1", "intent": "ship", "status": TaskStatus.IN_PROGRESS}
    base.update(over)
    return Task(**base)  # type: ignore[arg-type]


def test_standard_task_leaves_the_config_untouched() -> None:
    config = _config()
    out = apply_trust(config, task=_task(), policy=TrustPolicy())
    assert out.sandbox == "unrestricted" and out.permission_mode == "default"


def test_explicit_low_trust_clamps_to_read_only_plan() -> None:
    config = _config()
    task = _task(
        trust_preset=TrustPreset.LOW_TRUST_REVIEW.value,
        trust_boundary={"secret_ref_allowlist": ["ref:token"]},
    )
    out = apply_trust(config, task=task, policy=TrustPolicy())
    assert out.sandbox == "read-only"
    assert out.permission_mode == "plan"


def test_policy_derived_low_trust_clamps() -> None:
    config = _config()
    policy = TrustPolicy(low_trust_origins=frozenset({OriginKind.STRANDED_RECOVERY}))
    task = _task(
        origin_kind=OriginKind.STRANDED_RECOVERY,
        trust_boundary={"secret_ref_allowlist": []},
    )
    out = apply_trust(config, task=task, policy=policy)
    assert out.sandbox == "read-only"


def test_low_trust_without_a_boundary_is_denied() -> None:
    config = _config()
    task = _task(trust_preset=TrustPreset.LOW_TRUST_REVIEW.value)  # no boundary
    with pytest.raises(TrustDenied):
        apply_trust(config, task=task, policy=TrustPolicy())


def test_inline_secret_under_low_trust_is_denied() -> None:
    config = _config(env=(("GITHUB_TOKEN", "ghp_rawvalue"),))
    task = _task(
        trust_preset=TrustPreset.LOW_TRUST_REVIEW.value,
        trust_boundary={"secret_ref_allowlist": ["ref:token"]},
    )
    with pytest.raises(TrustDenied, match="inline secret"):
        apply_trust(config, task=task, policy=TrustPolicy())


def test_no_task_is_a_no_op() -> None:
    config = _config()
    assert apply_trust(config, task=None, policy=TrustPolicy()) is config
