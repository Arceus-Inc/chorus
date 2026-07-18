"""M3 — in-beat verdicts through the kernel (deterministic, no model).

Operator decision (2026-07-18): employees verify their own work — no system verifier. Every leaf
DoD is judged by dream's single in-beat evaluator (spec 16): one ``run_task`` renders the verdict
and lands the work ``done`` (or blocks it). There is no second Reviewer beat and no kernel evidence
machinery. Fake beat runners stand in for the worker / manager.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.heartbeat import IntegrateContextPacket, Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import (
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    Ledger,
    ManagementProfile,
    Task,
    TaskStatus,
    Team,
    TeamMember,
    TeamMembershipRole,
    TeamStatus,
)
from chorus.lifecycle import CapabilityService, ChildPlan, assign_task
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce
from chorus_employee import default_landers

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


class _Runner:
    def __init__(self, working_dir: Path) -> None:
        self._wd = working_dir

    @property
    def working_dir(self) -> Path:
        return self._wd


class _Worker(_Runner):
    """A leaf worker that renders its own verdict in-beat (spec 16): the DoD rubric is judged by
    dream's single in-beat evaluator, so the worker beat itself passes or blocks — there is no second
    Reviewer beat. ``decide(task_id)`` selects the verdict (default: always pass)."""

    def __init__(self, working_dir: Path, *, decide: object = None) -> None:
        super().__init__(working_dir)
        self._decide = decide

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        passed = True if self._decide is None else bool(self._decide(task_id))  # type: ignore[operator]
        return BeatOutcome(passed=passed, outcome={}, summary="produced", model="m")


class _Manager(_Runner):
    """Decompose on kickoff; on integrate, react when the kernel recommends it, else accept."""

    def __init__(self, ledger: Ledger, *, parent: str, working_dir: Path) -> None:
        super().__init__(working_dir)
        self._ledger = ledger
        self._parent = parent

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        svc = CapabilityService(self._ledger)
        if not self._ledger.tasks.has_children(self._parent):
            svc.decompose(
                parent_id=self._parent,
                revision=str(run_id),
                children=[ChildPlan(label="draft", intent="draft the spec", assignee=uid("pen"))],
                actor_employee_id="moe",
            )
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
        if IntegrateContextPacket.recommended_for(self._ledger, self._parent) == "react":
            rejected_id = next(
                child.id
                for child in self._ledger.tasks.children(self._parent)
                if child.status is TaskStatus.REJECTED
            )
            svc.submit_one(
                parent_id=self._parent,
                revision=str(run_id),
                child=ChildPlan(
                    label="redraft",
                    intent="redraft the spec",
                    assignee=uid("paul"),
                    replaces_task_id=rejected_id,
                ),
                actor_employee_id="moe",
            )
            return BeatOutcome(
                passed=False, outcome={}, summary="reacted to the rejection", model="m"
            )
        return BeatOutcome(passed=True, outcome={}, summary="accepted", model="m")


class _Org:
    """A fake harness factory: a role-faithful fake runner per employee."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        root: Path,
        parent: str = uid("M"),
        worker_decide: object = None,
    ) -> None:
        self._ledger = ledger
        self._root = root
        self._parent = parent
        self._worker_decide = (
            worker_decide  # spec 16: a worker renders its verdict in-beat
        )

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> object:
        profile = self._ledger.management_profiles.get(employee.id)
        if profile is not None and profile.active:
            return _Manager(self._ledger, parent=self._parent, working_dir=self._root)
        return _Worker(self._root, decide=self._worker_decide)


def _sched(ledger: Ledger, org: _Org, root: Path, *, max_review_rounds: int = 2) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=org,  # type: ignore[arg-type]
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=default_landers(root, ledger=ledger),
        clock=lambda: _NOW,
        max_concurrent_runs=4,
        max_review_rounds=max_review_rounds,
    )


async def test_approve_lands_the_deliverable_done(ledger: Ledger, tmp_path: Path) -> None:
    # Spec 16: an ``agent_review`` deliverable is judged by dream's single in-beat evaluator — one
    # ``run_task`` renders the verdict and lands the work ``done``. There is no second Reviewer beat,
    # so no ``rev_`` run row and no separate kernel-recorded verdict artifact.
    ledger.employees.create(Employee(id=uid("pen"), name="Pen", role="pm"))
    ledger.tasks.submit(Task(id=uid("spec"), intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, uid("spec"), uid("pen"))
    org = _Org(ledger, root=tmp_path)
    sched = _sched(ledger, org, tmp_path)

    await sched.tick_once()
    await sched.drain()

    assert ledger.tasks.get(uid("spec")).status is TaskStatus.DONE  # type: ignore[union-attr]
    assert not [
        r for r in ledger.runs.for_task(uid("spec")) if r.principal_kind == "system"
    ]  # one run, no review beat
    assert not [a for a in ledger.artifacts.list_for_task(uid("spec")) if a.type.value == "verdict"]


async def test_passed_backend_engineer_leaf_lands_done_with_no_system_verifier_run(
    ledger: Ledger, tmp_path: Path
) -> None:
    """Operator decision (2026-07-18): employees verify their own work — no system verifier.

    A backend-engineer leaf inherits its role DoD (a self-judged ``agent_review``); the in-beat
    evaluation IS the verdict, so a passed beat lands ``done`` with no second beat and no run row
    where ``principal_kind='system'``."""
    ledger.employees.create(Employee(id="dev", name="Dev", role="backend_engineer"))
    ledger.tasks.submit(Task(id=uid("code"), intent="build the widget", status=TaskStatus.TODO))
    assign_task(ledger, uid("code"), "dev")
    org = _Org(ledger, root=tmp_path)
    sched = _sched(ledger, org, tmp_path)

    await sched.tick_once()
    await sched.drain()

    assert ledger.tasks.get(uid("code")).status is TaskStatus.DONE  # type: ignore[union-attr]
    assert not [r for r in ledger.runs.for_task(uid("code")) if r.principal_kind == "system"]


async def test_standalone_block_self_repairs_then_opens_recovery(
    ledger: Ledger, tmp_path: Path
) -> None:
    # Spec 16: an ``agent_review`` block is the in-beat evaluator's needs-changes verdict. A standalone
    # deliverable climbs the bounded self-repair ladder (re-wake the author), then opens a recovery card.
    ledger.employees.create(Employee(id=uid("pen"), name="Pen", role="pm"))
    ledger.tasks.submit(Task(id=uid("spec"), intent="write the spec", status=TaskStatus.TODO))
    assign_task(ledger, uid("spec"), uid("pen"))
    org = _Org(
        ledger, root=tmp_path, worker_decide=lambda _tid: False
    )  # the in-beat evaluator always blocks
    sched = _sched(ledger, org, tmp_path)

    for _ in range(6):  # produce → block → self-repair (≤cap) → … → recovery card past the cap
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get(uid("spec")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert (
        ledger.recovery_actions.active_for_source(uid("spec")) is not None
    )  # bounded, then a human


async def test_delegation_rejection_reacts_once_then_escalates_without_force_acceptance(
    ledger: Ledger, tmp_path: Path
) -> None:
    # A rejected child remains part of the durable subtree. The lead may submit one correction, but
    # cannot force acceptance when the deterministic descendants check still sees the rejected attempt.
    ledger.employees.create(Employee(id="moe", name="Moe", role="pm"))
    ledger.employees.create(Employee(id=uid("pen"), name="Pen", role="pm", reports_to="moe"))
    ledger.employees.create(Employee(id=uid("paul"), name="Paul", role="pm", reports_to="moe"))
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="moe",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            max_delegation_depth=1,
            max_team_size=3,
            allowed_professions=("pm",),
        )
    )
    ledger.goals.create(Goal(id=uid("goal-M"), title="Ship the spec"))
    ledger.teams.create(
        Team(
            id=uid("team-M"),
            name="Spec Team",
            lead_employee_id="moe",
            created_by="operator",
            goal_id=uid("goal-M"),
            status=TeamStatus.ACTIVE,
        )
    )
    for employee_id, membership_role in (
        ("moe", TeamMembershipRole.LEAD),
        (uid("pen"), TeamMembershipRole.MEMBER),
        (uid("paul"), TeamMembershipRole.MEMBER),
    ):
        ledger.team_members.add(
            TeamMember(
                team_id=uid("team-M"),
                employee_id=employee_id,
                source_manager_id="moe",
                membership_role=membership_role,
            )
        )
    ledger.tasks.submit(
        Task(
            id=uid("M"),
            intent="ship the spec",
            status=TaskStatus.TODO,
            goal_id=uid("goal-M"),
            execution_mode=ExecutionMode.DELEGATION,
            team_id=uid("team-M"),
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id=uid("M"),
            team_id=uid("team-M"),
            lead_employee_id="moe",
            management_profile_version=1,
            objective_rubric="the complete spec is reviewed",
            max_depth=1,
            max_team_size=3,
            status=DelegationContractStatus.DELEGATED,
        )
    )
    assign_task(ledger, uid("M"), "moe")

    def decide(task_id: str) -> bool:
        task = ledger.tasks.get(task_id)
        return task is not None and task.origin_fingerprint != "draft"  # block only the first draft

    org = _Org(ledger, root=tmp_path, parent=uid("M"), worker_decide=decide)
    sched = _sched(ledger, org, tmp_path)

    for _ in range(12):
        await sched.tick_once()
        await sched.drain()

    children = {c.origin_fingerprint: c for c in ledger.tasks.children(uid("M"))}
    assert children["draft"].status is TaskStatus.REJECTED  # in-beat block → terminal-rejected
    assert children["redraft"].status is TaskStatus.DONE
    assert len(children) == 2
    assert ledger.tasks.get(uid("M")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    contract = ledger.delegation_contracts.get(uid("M"))
    assert contract is not None and contract.status is DelegationContractStatus.BLOCKED
    recovery = ledger.recovery_actions.active_for_source(uid("M"))
    assert recovery is not None and recovery.cause == "integrate_iteration_exhausted"


def test_worktree_file_manifest_lists_the_files_a_listless_reviewer_cannot_see(
    tmp_path: Path,
) -> None:
    # The reviewer's toolset is (read_file, submit_verdict) — no directory listing. The kernel must hand
    # it the actual file manifest, or it guesses standard manifest names, never finds app.py/test_app.py,
    # and wrongly declares the worktree empty (the live-reviewer-blocks-clean-code bug).
    from chorus.heartbeat._scheduler import _worktree_file_manifest

    (tmp_path / "app.py").write_text("def slugify(s): return s\n")
    (tmp_path / "test_app.py").write_text("from app import slugify\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_text("x = 1\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".harness" / "roles").mkdir(parents=True)  # kernel-injected, not the author's work
    (tmp_path / ".harness" / "roles" / "reviewer.toml").write_text("x = 1\n")
    (tmp_path / ".dream").mkdir()
    (tmp_path / ".dream" / "registry.json").write_text("{}\n")

    manifest = _worktree_file_manifest(tmp_path)

    assert "app.py" in manifest
    assert "test_app.py" in manifest
    assert "pkg/util.py" in manifest
    assert ".git" not in manifest  # internal git plumbing is never review material
    assert ".harness" not in manifest  # kernel harness injection is identical in every worktree
    assert ".dream" not in manifest


def test_worktree_file_manifest_is_empty_for_no_worktree() -> None:
    from chorus.heartbeat._scheduler import _worktree_file_manifest

    assert _worktree_file_manifest(None) == ""
