"""M3 — the manager's two-phase lifecycle through the kernel (spec M3 §5, deterministic).

A decompose beat is a *fifth* outcome: it neither passed, failed its DoD, errored, nor cancelled — it
**succeeded by delegating**, so the parent is PARKED (``blocked``, waiting on its children), never
stranded onto the recovery ladder. When the children finish, ``children_done`` re-invokes the manager
with an integrate context packet; the manager can accept the subtree or submit/assign one bounded
follow-up. No model: a fake beat runner stands in for the manager (decomposing via the live
:class:`CapabilityService`) and the engineers.
"""

from __future__ import annotations

from datetime import UTC, datetime

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

_NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


class _PassingVerifier:
    async def run_task(self, **_: object) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="independently verified", model="m")


class _RunnerFactory:
    def __init__(self, beat: object) -> None:
        self._beat = beat
        self._verifier = _PassingVerifier()

    def runner_for(self, employee: Employee, *, task_id: str) -> object:
        return self._beat

    def verification_runner_for(
        self, reviewer: Employee, *, task_id: str, worktree_owner_id: str
    ) -> object:
        return self._verifier


class _TeamBeat:
    """A fake beat: on the manager's parent it decomposes once (via the real CapabilityService) into
    two assigned children; every other beat (the children, the manager's integrate re-invocation) just
    passes. The parent beats return ``passed=False`` to prove park/integrate ignore the dream verdict."""

    def __init__(self, ledger: Ledger, *, parent: str) -> None:
        self._ledger = ledger
        self._parent = parent
        self.ran: list[str] = []
        self.integrate_packets: list[IntegrateContextPacket] = []
        self.submission_results: list[object] = []
        self.working_dir = None

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
        self.ran.append(task_id)
        if task_id == self._parent:
            if not self._ledger.tasks.has_children(self._parent):  # the decompose beat
                CapabilityService(self._ledger).decompose(
                    parent_id=self._parent,
                    revision=str(run_id),
                    children=[
                        ChildPlan(label="api", intent="build the api", assignee="ada"),
                        ChildPlan(
                            label="ui", intent="build the ui", assignee="bob", depends_on=("api",)
                        ),
                    ],
                    actor_employee_id="mgr",
                )
                return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
            assert self.working_dir is not None
            self.integrate_packets.append(IntegrateContextPacket.read(self.working_dir))
            return BeatOutcome(passed=True, outcome={}, summary="accepted subtree", model="m")
        return BeatOutcome(passed=True, outcome={}, summary="ok", model="m")


def _delegated_parent(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="backend_engineer"))
    ledger.employees.create(
        Employee(id="ada", name="Ada", role="backend_engineer", reports_to="mgr")
    )
    ledger.employees.create(
        Employee(id="bob", name="Bob", role="backend_engineer", reports_to="mgr")
    )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="mgr",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            max_delegation_depth=2,
            max_team_size=3,
            allowed_professions=("backend_engineer",),
        )
    )
    ledger.goals.create(Goal(id=uid("goal-M"), title="Ship the feature"))
    ledger.teams.create(
        Team(
            id=uid("team-M"),
            name="Feature Team",
            lead_employee_id="mgr",
            created_by="operator",
            goal_id=uid("goal-M"),
            status=TeamStatus.ACTIVE,
        )
    )
    for employee_id, membership_role in (
        ("mgr", TeamMembershipRole.LEAD),
        ("ada", TeamMembershipRole.MEMBER),
        ("bob", TeamMembershipRole.MEMBER),
    ):
        ledger.team_members.add(
            TeamMember(
                team_id=uid("team-M"),
                employee_id=employee_id,
                source_manager_id="mgr",
                membership_role=membership_role,
            )
        )
    ledger.tasks.submit(
        Task(
            id=uid("M"),
            intent="ship the feature",
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
            lead_employee_id="mgr",
            management_profile_version=1,
            objective_rubric="the full feature is integrated and independently verified",
            max_depth=2,
            max_team_size=3,
            status=DelegationContractStatus.DELEGATED,
        )
    )
    assign_task(ledger, uid("M"), "mgr")


def _objective_roles() -> RoleRegistry:
    """Default roles with an objective backend-engineer gate for park/integrate tests."""
    from chorus.outcomes import Verifier
    from chorus.roles._plugin import RolePlugin

    base = default_roles()
    engineer = next(p for p in base if p.name == "backend_engineer")
    others = tuple(p for p in base if p.name != "backend_engineer")
    objective = RolePlugin(
        name="backend_engineer",
        manifest=engineer.manifest,
        dod_generator=lambda intent: Verifier.command("true", artifact_class="pr"),
        outcome_kind=engineer.outcome_kind,
    )
    return RoleRegistry.from_plugins((*others, objective))


def _sched(ledger: Ledger, beat: _TeamBeat, *, tmp_path: object = None) -> Scheduler:
    from pathlib import Path

    root = Path(str(tmp_path)) if tmp_path is not None else Path(".")
    beat.working_dir = root
    return Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=_RunnerFactory(beat),  # type: ignore[arg-type]
        roles=_objective_roles(),
        landers=default_landers(
            root, ledger=ledger
        ),  # the manager lands a subtree artifact on integrate
        clock=lambda: _NOW,
        max_concurrent_runs=4,
    )


async def test_decompose_beat_parks_the_parent_not_strands_it(ledger: Ledger) -> None:
    _delegated_parent(ledger)
    beat = _TeamBeat(ledger, parent=uid("M"))
    sched = _sched(ledger, beat)

    await sched.tick_once()  # the manager's decompose beat
    await sched.drain()

    parent = ledger.tasks.get(uid("M"))
    assert parent is not None and parent.status is TaskStatus.BLOCKED  # PARKED, not failed
    contract = ledger.delegation_contracts.get(uid("M"))
    assert contract is not None and contract.status is DelegationContractStatus.DELEGATED
    assert (
        ledger.recovery_actions.active_for_source(uid("M")) is None
    )  # never stranded onto recovery
    # the two children exist, assigned, gating the parent
    assert set(
        ledger.dependencies.unresolved_blockers(uid("M"))
    ) and not ledger.tasks.all_children_terminal(uid("M"))


async def test_full_loop_decompose_then_children_then_integrate_to_done(
    ledger: Ledger, tmp_path: object
) -> None:
    _delegated_parent(ledger)
    beat = _TeamBeat(ledger, parent=uid("M"))
    sched = _sched(ledger, beat, tmp_path=tmp_path)

    for _ in range(6):  # decompose → api → ui → children_done → integrate
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get(uid("M")).status is TaskStatus.DONE  # type: ignore[union-attr]  # integrated
    assert ledger.tasks.all_children_terminal(uid("M"))  # the whole subtree landed
    assert beat.ran.count(uid("M")) == 2  # decompose beat, then real integrate beat
    contract = ledger.delegation_contracts.get(uid("M"))
    assert contract is not None and contract.status is DelegationContractStatus.DONE
    assert len(beat.integrate_packets) == 1
    assert {child.assignee for child in beat.integrate_packets[0].children} == {"ada", "bob"}
    # the ManagerLander recorded the subtree as the manager's primary deliverable
    subtree = next(
        a
        for a in ledger.artifacts.list_for_task(uid("M"))
        if a.resource_ref is not None and a.resource_ref.get("kind") == "subtree"
    )
    assert {c["id"] for c in subtree.resource_ref["children"]} == {  # type: ignore[union-attr,index]
        c.id for c in ledger.tasks.children(uid("M"))
    }


class _AdaptiveBeat:
    """Decompose on kickoff; on integrate #1 submit ONE follow-up child; on integrate #2 accept."""

    def __init__(self, ledger: Ledger, *, parent: str) -> None:
        self._ledger = ledger
        self._parent = parent
        self.ran: list[str] = []
        self.integrate_packets: list[IntegrateContextPacket] = []
        self.submission_results: list[object] = []
        self.working_dir: object = None
        self._integrates = 0

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
        self.ran.append(task_id)
        svc = CapabilityService(self._ledger)
        if task_id != self._parent:
            return BeatOutcome(
                passed=True, outcome={}, summary="ok", model="m"
            )  # an engineer child
        if not self._ledger.tasks.has_children(self._parent):  # kickoff beat
            svc.decompose(
                parent_id=self._parent,
                revision=str(run_id),
                children=[
                    ChildPlan(label="api", intent="api", assignee="ada"),
                    ChildPlan(label="ui", intent="ui", assignee="bob"),
                ],
                actor_employee_id="mgr",
            )
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
        self._integrates += 1
        from pathlib import Path

        self.integrate_packets.append(IntegrateContextPacket.read(Path(str(self.working_dir))))
        if self._integrates == 1:  # react: one concrete follow-up
            submitted = svc.submit_one(
                parent_id=self._parent,
                revision=str(run_id),
                child=ChildPlan(label="polish", intent="polish", assignee="ada"),
                actor_employee_id="mgr",
            )
            self.submission_results.append(submitted)
            assert submitted.child_id is not None, submitted
            return BeatOutcome(passed=False, outcome={}, summary="submitted follow-up", model="m")
        return BeatOutcome(passed=True, outcome={}, summary="accepted", model="m")  # integrate #2


class _AlwaysSubmitBeat:
    """A misbehaving manager: decompose on kickoff, then submit a fresh follow-up on EVERY integrate."""

    def __init__(self, ledger: Ledger, *, parent: str) -> None:
        self._ledger = ledger
        self._parent = parent
        self.ran: list[str] = []
        self.working_dir: object = None
        self._n = 0

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
        self.ran.append(task_id)
        svc = CapabilityService(self._ledger)
        if task_id != self._parent:
            return BeatOutcome(passed=True, outcome={}, summary="ok", model="m")
        if not self._ledger.tasks.has_children(self._parent):
            svc.decompose(
                parent_id=self._parent,
                revision=str(run_id),
                children=[ChildPlan(label="c0", intent="c0", assignee="ada")],
                actor_employee_id="mgr",
            )
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="m")
        self._n += 1
        submitted = svc.submit_one(
            parent_id=self._parent,
            revision=str(run_id),
            child=ChildPlan(label=f"more{self._n}", intent="more", assignee="ada"),
            actor_employee_id="mgr",
        )
        assert submitted.child_id is not None, submitted
        return BeatOutcome(passed=False, outcome={}, summary="never accepts", model="m")


def _adaptive_sched(ledger: Ledger, beat: object, root: object, *, cap: int = 3) -> Scheduler:
    from pathlib import Path

    beat.working_dir = Path(str(root))  # type: ignore[attr-defined]
    return Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=_RunnerFactory(beat),  # type: ignore[arg-type]
        roles=_objective_roles(),
        landers=default_landers(Path(str(root)), ledger=ledger),
        clock=lambda: _NOW,
        max_concurrent_runs=4,
        max_integrate_iterations=cap,
    )


async def test_adaptive_integrate_submits_a_follow_up_then_re_integrates_to_done(
    ledger: Ledger, tmp_path: object
) -> None:
    _delegated_parent(ledger)
    beat = _AdaptiveBeat(ledger, parent=uid("M"))
    sched = _adaptive_sched(ledger, beat, tmp_path)

    for _ in range(
        12
    ):  # kickoff → api,ui → integrate#1 (submit polish) → polish → integrate#2 (accept)
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get(uid("M")).status is TaskStatus.DONE  # type: ignore[union-attr]
    assert all(result.child_id is not None for result in beat.submission_results), (
        beat.submission_results
    )
    assert len(ledger.tasks.children(uid("M"))) == 3  # api, ui, + the submitted polish
    assert ledger.tasks.all_children_terminal(uid("M"))
    # the manager REACTED: kickoff + integrate#1 (submitted) + integrate#2 (accepted) = 3 model beats
    assert beat.ran.count(uid("M")) == 3
    # the real iteration count is threaded into the packet
    assert [p.iteration for p in beat.integrate_packets] == [1, 2]


async def test_adaptive_integrate_cap_escalates_without_force_acceptance(
    ledger: Ledger, tmp_path: object
) -> None:
    _delegated_parent(ledger)
    beat = _AlwaysSubmitBeat(ledger, parent=uid("M"))
    sched = _adaptive_sched(
        ledger, beat, tmp_path, cap=2
    )  # bound the loop at 2 adaptive integrates

    for _ in range(30):  # a manager that never accepts must still terminate
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get(uid("M")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    contract = ledger.delegation_contracts.get(uid("M"))
    assert contract is not None and contract.status is DelegationContractStatus.BLOCKED
    recovery = ledger.recovery_actions.active_for_source(uid("M"))
    assert recovery is not None and recovery.cause == "integrate_iteration_exhausted"
    # kickoff + exactly cap(=2) adaptive integrate beats; the 3rd integrate was capped (mechanical, no beat)
    assert beat.ran.count(uid("M")) == 3


# -- the objective rollup gate (run-18 false-`done` fix) -------------------------------------------
#
# A delegated parent integrates *mechanically* — landed ``done`` the instant its subtree is terminal.
# When the goal carries an OBJECTIVE ``command`` DoD (e.g. "every required deliverable exists and the
# gate passes"), that command is the structural rollup gate: the kernel runs it in the integrator's
# worktree and parks the goal BLOCKED (not ``done``) if it fails, so a half-built decomposition surfaces
# honestly instead of being laundered into a false ``done``.

_PY_FAIL = (
    'python -c "import sys; sys.exit(1)"'  # a failing objective floor (a deliverable is missing)
)
_PY_PASS = (
    'python -c "import sys; sys.exit(0)"'  # a passing objective floor (the goal is satisfied)
)


async def test_integrate_blocks_when_the_goals_objective_rollup_floor_fails(
    ledger: Ledger, tmp_path: object
) -> None:
    from chorus.ledger import DodStatus
    from chorus.outcomes import Verifier

    _delegated_parent(ledger)
    ledger.dod.create(
        uid("M"), Verifier.command(_PY_FAIL)
    )  # the goal's objective rollup floor FAILS
    beat = _TeamBeat(ledger, parent=uid("M"))
    sched = _sched(ledger, beat, tmp_path=tmp_path)

    for _ in range(6):  # decompose → api → ui → children_done → integrate
        await sched.tick_once()
        await sched.drain()

    parent = ledger.tasks.get(uid("M"))
    assert (
        parent is not None and parent.status is TaskStatus.BLOCKED
    )  # NOT done — the floor rejected it
    assert ledger.tasks.all_children_terminal(uid("M"))  # the subtree still fully landed
    dod = ledger.dod.get_for_task(uid("M"))
    assert (
        dod is not None and dod.status is DodStatus.FAILED
    )  # the failing rollup verdict is recorded


async def test_integrate_lands_done_when_the_objective_rollup_floor_passes(
    ledger: Ledger, tmp_path: object
) -> None:
    from chorus.outcomes import Verifier

    _delegated_parent(ledger)
    ledger.dod.create(
        uid("M"), Verifier.command(_PY_PASS)
    )  # the goal's objective rollup floor PASSES
    beat = _TeamBeat(ledger, parent=uid("M"))
    sched = _sched(ledger, beat, tmp_path=tmp_path)

    for _ in range(6):
        await sched.tick_once()
        await sched.drain()

    assert ledger.tasks.get(uid("M")).status is TaskStatus.DONE  # type: ignore[union-attr]  # floor passed → done
    assert ledger.tasks.all_children_terminal(uid("M"))
