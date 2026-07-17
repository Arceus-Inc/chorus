"""M8 capstone: specialist-led nested delegation through the real scheduler."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import (
    ActivityVerb,
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    Ledger,
    ManagementProfile,
    Task,
    TaskStatus,
    TeamStatus,
)
from chorus.lifecycle import CapabilityService, ChildPlan, MissionTeamPolicy, assign_task
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce
from chorus_employee import default_landers

# The sibling horizon checkout lives NEXT TO this repo (…/chorus/tests/heartbeat/x.py →
# parents[2] is the repo root, parents[3] its parent). Skip — not fail collection — when
# horizon isn't checked out or importable, so the rest of the suite still runs.
_HORIZON_SRC = Path(__file__).resolve().parents[3] / "horizon" / "src"
if _HORIZON_SRC.is_dir() and str(_HORIZON_SRC) not in sys.path:
    sys.path.insert(0, str(_HORIZON_SRC))

pytest.importorskip("horizon", reason="sibling horizon checkout not available")

from horizon.feedback import OutcomeFold  # noqa: E402
from horizon.model import StrategyRecord  # noqa: E402
from horizon.ports import OutcomeEvent  # noqa: E402

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)


class _Runner:
    def __init__(self, org: _CapstoneOrg, employee_id: str, working_dir: Path) -> None:
        self._org = org
        self._employee_id = employee_id
        self.working_dir = working_dir

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: str = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        return self._org.run(self._employee_id, task_id, str(run_id))


class _CapstoneOrg:
    def __init__(self, ledger: Ledger, working_dir: Path, strategy: StrategyRecord) -> None:
        self._ledger = ledger
        self._working_dir = working_dir
        self._strategy = strategy
        self._fold = OutcomeFold()
        self.injected_failures = 0
        self.reactions: list[str] = []
        self.unauthorized_results: list[tuple[str | None, int, int]] = []
        self.retry_child_ids: list[tuple[dict[str, str], dict[str, str]]] = []
        self.health_after_failure: str | None = None
        self.verification_snapshots: list[tuple[str, tuple[TaskStatus, ...]]] = []

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> _Runner:
        return _Runner(self, employee.id, self._working_dir)

    def run(self, employee_id: str, task_id: str, run_id: str) -> BeatOutcome:
        task = self._ledger.tasks.get(task_id)
        assert task is not None
        if task.execution_mode is ExecutionMode.DELEGATION:
            return self._run_delegation(employee_id, task, run_id)
        if task.origin_fingerprint == "nested-implementation" and self.injected_failures == 0:
            self.injected_failures += 1
            self._fold.apply(
                self._strategy,
                OutcomeEvent(
                    kind="run.evaluated",
                    task_id=task.id,
                    root_task_id=uid("root"),
                    passed=False,
                ),
            )
            self.health_after_failure = self._strategy.health
            return BeatOutcome(passed=False, outcome={}, summary="injected failure", model="fake")
        return BeatOutcome(passed=True, outcome={}, summary="delivery passed", model="fake")

    def _run_delegation(self, employee_id: str, task: Task, run_id: str) -> BeatOutcome:
        service = CapabilityService(self._ledger)
        children = self._ledger.tasks.children(task.id)
        if not children:
            plan = self._plan_for(task.id)
            before = len(self._ledger.tasks.children(task.id))
            denied = service.decompose(
                parent_id=task.id,
                revision=f"forged-{run_id}",
                children=plan,
                actor_employee_id=uid("outsider"),
            )
            after = len(self._ledger.tasks.children(task.id))
            self.unauthorized_results.append((denied.authority_denied, before, after))
            first = service.decompose(
                parent_id=task.id,
                revision=run_id,
                children=plan,
                actor_employee_id=employee_id,
            )
            retry = service.decompose(
                parent_id=task.id,
                revision=run_id,
                children=plan,
                actor_employee_id=employee_id,
            )
            self.retry_child_ids.append((first.child_ids, retry.child_ids))
            return BeatOutcome(passed=False, outcome={}, summary="delegated", model="fake")

        if task.id != uid("root"):
            correction = next(
                (child for child in children if child.origin_fingerprint == "nested-correction"),
                None,
            )
            if correction is None:
                result = service.submit_one(
                    parent_id=task.id,
                    revision=run_id,
                    child=ChildPlan(
                        label="nested-correction",
                        intent="correct and independently re-check the nested implementation",
                        assignee=uid("nested-worker"),
                        replaces_task_id=next(
                            child.id for child in children if child.status is TaskStatus.REJECTED
                        ),
                    ),
                    actor_employee_id=employee_id,
                )
                assert result.child_id is not None
                self.reactions.append(task.id)
                return BeatOutcome(
                    passed=False, outcome={}, summary="correction submitted", model="fake"
                )

        statuses = tuple(child.status for child in self._ledger.tasks.children(task.id))
        self.verification_snapshots.append((task.id, statuses))
        verified = (
            TaskStatus.DONE in statuses
            and all(status in {TaskStatus.DONE, TaskStatus.REJECTED} for status in statuses)
            and (
                task.id == uid("root")
                or any(
                    child.origin_fingerprint == "nested-correction"
                    and child.status is TaskStatus.DONE
                    for child in self._ledger.tasks.children(task.id)
                )
            )
        )
        if verified and task.id == uid("root"):
            self._fold.apply(
                self._strategy,
                OutcomeEvent(
                    kind="run.evaluated",
                    task_id=task.id,
                    root_task_id=task.id,
                    passed=True,
                    is_root_outcome=True,
                ),
            )
        return BeatOutcome(
            passed=verified,
            outcome={"independent_verification": verified},
            summary="objective gate passed" if verified else "objective gate failed",
            model="fake",
        )

    @staticmethod
    def _plan_for(task_id: str) -> tuple[ChildPlan, ...]:
        if task_id == uid("root"):
            return (
                ChildPlan(
                    label="nested-area",
                    intent="lead the nested implementation area",
                    assignee="nested-lead",
                    execution_mode=ExecutionMode.DELEGATION,
                    can_subdelegate=True,
                ),
                ChildPlan(
                    label="launch-plan",
                    intent="prepare the launch plan",
                    assignee=uid("launch-owner"),
                ),
            )
        return (
            ChildPlan(
                label="nested-implementation",
                intent="deliver the nested implementation",
                assignee=uid("nested-worker"),
            ),
        )


def _seed_company(ledger: Ledger) -> None:
    employees = (
        Employee(id="root-lead", name="Root Lead", role="backend_engineer"),
        Employee(
            id="nested-lead",
            name="Nested Lead",
            role="designer",
            reports_to="root-lead",
        ),
        Employee(
            id=uid("launch-owner"),
            name="Launch Owner",
            role="pm",
            reports_to="root-lead",
        ),
        Employee(
            id=uid("nested-worker"),
            name="Nested Worker",
            role="pm",
            reports_to="nested-lead",
        ),
    )
    for employee in employees:
        ledger.employees.create(employee)
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="root-lead",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=2,
            max_team_size=3,
            allowed_professions=("designer", "pm"),
        )
    )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="nested-lead",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=1,
            max_team_size=2,
            allowed_professions=("pm",),
        )
    )
    ledger.goals.create(Goal(id=uid("goal-capstone"), title="Ship the capstone"))
    team = MissionTeamPolicy(ledger).create_for_root(
        ledger.employees.get("root-lead"),  # type: ignore[arg-type]
        uid("goal-capstone"),
    )
    MissionTeamPolicy(ledger).activate(team.id)
    ledger.tasks.submit(
        Task(
            id=uid("root"),
            intent="ship the complete nested delegation outcome",
            status=TaskStatus.TODO,
            execution_mode=ExecutionMode.DELEGATION,
            team_id=team.id,
            goal_id=uid("goal-capstone"),
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id=uid("root"),
            team_id=team.id,
            lead_employee_id="root-lead",
            management_profile_version=1,
            can_subdelegate=True,
            max_depth=2,
            max_team_size=3,
            objective_rubric="all required areas are corrected, integrated, and verified",
            status=DelegationContractStatus.DELEGATED,
        )
    )
    assign_task(ledger, uid("root"), "root-lead")


async def test_specialist_nested_delegation_capstone_folds_verified_root_exactly_once(
    ledger: Ledger, tmp_path: Path
) -> None:
    _seed_company(ledger)
    strategy = StrategyRecord(
        goal_id=uid("goal-capstone"),
        root_task_id=uid("root"),
        task_ids=[uid("root")],
        delivery_shape="team",
    )
    org = _CapstoneOrg(ledger, tmp_path, strategy)
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=org,  # type: ignore[arg-type]
        roles=RoleRegistry.from_plugins(default_roles()),
        landers=default_landers(tmp_path, ledger=ledger),
        clock=lambda: _NOW,
        max_concurrent_runs=1,
        max_integrate_iterations=3,
    )

    for _ in range(24):
        await scheduler.tick_once()
        await scheduler.drain()
        if ledger.tasks.get(uid("root")).status is TaskStatus.DONE:  # type: ignore[union-attr]
            break

    employees = ledger.employees.list()
    tasks = ledger.tasks.all()
    contracts = ledger.delegation_contracts.list()
    assert all(employee.role != "manager" for employee in employees)
    assert org.injected_failures == 1
    assert org.reactions == [
        next(task.id for task in tasks if task.origin_fingerprint == "nested-area")
    ]
    assert org.health_after_failure == "drifting"
    assert strategy.done is True and strategy.health == "on_track"
    assert ledger.tasks.get(uid("root")).status is TaskStatus.DONE  # type: ignore[union-attr]
    assert len(contracts) == 2
    assert all(contract.status is DelegationContractStatus.DONE for contract in contracts)
    assert all(first == retry for first, retry in org.retry_child_ids)
    assert all(
        reason == "actor is not the delegation contract lead" and before == after == 0
        for reason, before, after in org.unauthorized_results
    )
    assert len({task.id for task in tasks}) == len(tasks)
    assert all(
        task.id == uid("root")
        or (task.parent_id is not None and ledger.tasks.get(task.parent_id) is not None)
        for task in tasks
    )
    assert len([task for task in tasks if task.origin_fingerprint == "nested-correction"]) == 1
    assert all(task.assignee_employee_id != "system-verifier" for task in tasks)
    assert all(team.status is TeamStatus.ARCHIVED for team in ledger.teams.list())
    verified = [
        event
        for contract in contracts
        for event in ledger.activity.by_subject("delegation_contract", contract.task_id)
        if event.verb is ActivityVerb.PARENT_VERIFIED
    ]
    assert len(verified) == 2 and all(event.payload["passed"] is True for event in verified)
    assert all(event.payload["reviewer_id"] == "system-verifier" for event in verified)
    verification_runs = [
        ledger.runs.get(str(event.payload["verification_run_id"])) for event in verified
    ]
    assert all(run is not None for run in verification_runs)
    assert all(
        run.principal_id == "system-verifier"
        and run.employee_id in {"root-lead", "nested-lead"}
        and run.lease_expires_at is not None
        and run.finished_at is not None
        for run in verification_runs
        if run is not None
    )
    assert {str(event.payload["verification_run_id"]) for event in verified}.isdisjoint(
        {contract.accepted_run_id for contract in contracts}
    )
    assert {task_id for task_id, _ in org.verification_snapshots} == {
        contract.task_id for contract in contracts
    }
