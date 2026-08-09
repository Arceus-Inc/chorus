"""EmployeeHarnessFactory — the org's one role-faithful materializer (spec 06 §2 → dream seam).

dream's harness build is stubbed so the role → harness translation is tested without a provider; the
worktree side-effects run on real git in a temp dir.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from dream.contracts.hook import HookEvent
from dream.contracts.strategy import LandedPhase, RecoveryHint

from chorus.heartbeat import BeatRunner
from chorus.ledger import (
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Ledger,
    ManagementProfile,
    Run,
    RunCarryover,
    RunStatus,
    Task,
    TaskStatus,
    Team,
    TeamMember,
    TeamMembershipRole,
    TeamStatus,
)
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod
from chorus_harness._dream_hooks import VolatileBeatPacketHook

pytestmark = pytest.mark.integration


class _HarnessStub:
    def __init__(self) -> None:
        self.hooks: list[object] = []

    def register_hook(self, hook: object) -> None:
        self.hooks.append(hook)


def _factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger | None
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    harness = _HarnessStub()
    monkeypatch.setattr(
        _factory_mod.dream,
        "build_harness",
        lambda **kw: captured.update(kw) or captured.update(harness=harness) or harness,
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
        ledger=ledger,
    )
    return factory, captured


def _seed_delegation(ledger: Ledger, *, child_status: TaskStatus | None = None) -> Employee:
    lead = Employee(id="moe", name="Moe", role="backend_engineer")
    worker = Employee(id="ada", name="Ada", role="backend_engineer", reports_to=lead.id)
    ledger.employees.create(lead)
    ledger.employees.create(worker)
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id=lead.id,
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            max_delegation_depth=1,
            max_team_size=3,
            allowed_professions=("backend_engineer",),
            version=1,
        )
    )
    ledger.teams.create(
        Team(
            id=uid("team-goal"),
            name="Goal Team",
            lead_employee_id=lead.id,
            created_by="operator",
            status=TeamStatus.ACTIVE,
        )
    )
    for employee_id, membership_role in (
        (lead.id, TeamMembershipRole.LEAD),
        (worker.id, TeamMembershipRole.MEMBER),
    ):
        ledger.team_members.add(
            TeamMember(
                team_id=uid("team-goal"),
                employee_id=employee_id,
                source_manager_id=lead.id,
                membership_role=membership_role,
            )
        )
    ledger.tasks.submit(
        Task(
            id=uid("goal"),
            intent="ship it",
            status=TaskStatus.BLOCKED if child_status is not None else TaskStatus.TODO,
            execution_mode=ExecutionMode.DELEGATION,
            team_id=uid("team-goal"),
            assignee_employee_id=lead.id,
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id=uid("goal"),
            team_id=uid("team-goal"),
            lead_employee_id=lead.id,
            management_profile_version=1,
            max_depth=1,
            max_team_size=3,
            objective_rubric="integrate the delegated subtree",
            status=(
                DelegationContractStatus.INTEGRATING
                if child_status is not None
                else DelegationContractStatus.DELEGATED
            ),
        )
    )
    if child_status is not None:
        ledger.tasks.submit(
            Task(
                id=uid("kid"),
                intent="a part",
                status=child_status,
                parent_id=uid("goal"),
                assignee_employee_id=worker.id,
            )
        )
    return lead


def test_backend_engineer_materializes_a_writable_harness_in_its_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="backend_engineer"))
    # the engineer works confined to its own branch-isolated worktree under the org root
    assert mat.working_dir == tmp_path / "acme" / "worktrees" / "ada"
    assert mat.workspace is not None
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {
        "read_file",
        "read_offloaded",
        "write_file",
        "apply_patch",
        "bash",
        "git",
        "todo_write",
        "skill",
        "test_evidence",
        "test_red",
        "secret_scan",
        "code_quality",
        # spawn_subagent is no longer factory-registered: the strict-TDD gate is unwired (operator
        # decision 2026-07-18); dream's build_harness registers it from config.subagents at build time.
    }
    assert mat.config.permission_mode == "acceptEdits"
    assert captured["max_turns"] == 24  # the engine scalars come from the role too
    assert captured["working_memory"] is True
    assert captured["web"] is True
    assert captured["browser"] is True
    assert captured["code_intel"] is True
    assert mat.runner._subagent_evidence == {
        "test_author": ("test_plan.json", {"authored": True}, False),
        "code_reviewer": ("review_verdict.json", {"cleared": True}, True),
    }


def test_backend_engineer_materializes_subagent_evidence_when_opted_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    factory._stop_evidence_requirements = True
    mat = factory.materialize(Employee(id="ada", name="Ada", role="backend_engineer"))
    assert mat.runner._subagent_evidence == {
        "test_author": ("test_plan.json", {"authored": True}, False),
        "code_reviewer": ("review_verdict.json", {"cleared": True}, True),
    }


def test_role_registry_registers_the_read_file_offload_companion() -> None:
    from chorus_harness._factory import _role_registry

    names = {tool.name for tool in _role_registry(("read_file",)).list_tools()}
    assert names == {"read_file", "read_offloaded"}


def test_engineer_role_overlays_keep_evaluator_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # The evaluator keeps reads + bash but must treat generator-only tool instructions as evidence to
    # inspect, not unavailable actions to attempt. The planner is deliberately TOOLLESS (`tools = []`)
    # and the generator runs tools=null (no `tools =` line), so it sees the full role toolset.
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="backend_engineer"))

    planner = (mat.working_dir / ".harness" / "roles" / "planner.toml").read_text(encoding="utf-8")
    evaluator = (mat.working_dir / ".harness" / "roles" / "evaluator.toml").read_text(
        encoding="utf-8"
    )
    generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text(
        encoding="utf-8"
    )

    assert "tools = []" in planner  # toolless on purpose
    assert "PLANNER PHASE" in planner
    assert '"bash"' in evaluator  # in-session verify (no harness oracle)
    assert '"write_file"' not in evaluator
    assert "the sprint contract and review rubric are the acceptance authority" in evaluator
    assert "not extra acceptance criteria" in evaluator
    assert "tools =" not in generator


def test_engineer_gets_an_unrestricted_sandbox_so_it_can_run_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # the engineer must run tests/builds (arbitrary commands), which dream gates behind an interactive
    # approval the autonomous kernel can't supply — so its trust posture is unrestricted-in-worktree.
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="backend_engineer"))
    sandbox = (mat.working_dir / ".harness" / "sandbox.toml").read_text(encoding="utf-8")
    assert 'tier = "unrestricted"' in sandbox
    assert "confirm_unrestricted = true" in sandbox  # dream double-gates it; the choice is explicit
    assert mat.config.sandbox == "unrestricted"


def test_pm_materializes_its_skill_bundle_into_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # A role with skills (the PM) gets its bundle copied INTO the worktree, so the model can reach the
    # bundled reference files with its worktree-confined read_file — and dream's registry is pointed at
    # that in-worktree copy (skills enabled + a registry supplied).
    factory, captured = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id="pat", name="Pat", role="pm"))

    canvas = mat.working_dir / ".harness" / "skills" / "recommendation-canvas"
    assert (canvas / "SKILL.md").exists()
    # the bundled reference files the SKILL.md points at come across too — the whole reason for Option C
    assert (canvas / "template.md").exists()
    assert (canvas / "references" / "sample.md").exists()
    assert captured["skill_registry"] is not None
    assert captured["skills"] is True


def test_materialized_skill_bundle_is_git_excluded_from_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # The whole point of homing the bundle under .harness/: it is already excluded from every worktree
    # branch (chorus.workspace info/exclude), so a skill's files never get committed or merged as a
    # deliverable. git must not see .harness/skills as an untracked path.
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    mat = factory.materialize(Employee(id="pat", name="Pat", role="pm"))

    status = subprocess.run(
        ["git", "-C", str(mat.working_dir), "status", "--porcelain", "--ignored"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # excluded paths surface under `!!` (ignored), never as untracked `??`
    assert "?? .harness/skills" not in status
    assert not any(
        line.startswith("?? ") and ".harness/skills" in line for line in status.splitlines()
    )


def test_delegation_harness_registers_the_decompose_capability_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # The manager's leverage is the chorus `decompose` capability — a chorus-only tool with no dream
    # built-in. It is registered into the harness only when the factory has a ledger to bind it to.
    ledger = open_test_ledger()
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        lead = _seed_delegation(ledger)
        factory.materialize(lead, task_id=uid("goal"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert names == {
            "read_file",
            "read_offloaded",
            "decompose",
            "team_read",
            "staffing_request",
            "comment",  # coordination verbs ride every employee beat (OM-3)
            "read_comments",
        }
    finally:
        ledger.close()


def test_marketer_harness_registers_the_stage_go_live_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # The marketer's ONLY path to a live surface is the `stage_go_live` capability tool (§07/§11): a
    # chorus capability that opens a governance gate, with no dream built-in. It is registered into
    # the harness only when the factory has a ledger to bind it to — fail-closed otherwise.
    ledger = open_test_ledger()
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize(Employee(id="mira", name="Mira", role="marketer"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert "stage_go_live" in names  # her one gated live surface is wired
        assert (
            "decompose" not in names
        )  # she is not a delegator; go-live is her only capability tool
    finally:
        ledger.close()


def test_integrate_beat_harness_drops_the_decompose_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # Structural over-decompose guard (M3 §5): an integrate beat — the manager's task already has
    # children — is materialized WITHOUT `decompose`, so the model can react with submit_task /
    # assign_task but cannot re-decompose (and balloon) a delegated subtree. Brief discipline alone
    # is not enough; under load a manager re-decomposes.
    from chorus.ledger import TaskStatus

    ledger = open_test_ledger()
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        lead = _seed_delegation(ledger, child_status=TaskStatus.TODO)
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize(lead, task_id=uid("goal"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert "decompose" not in names  # cannot re-decompose a delegated subtree
        assert {"read_file", "submit_task", "assign_task"} <= names  # the reactive toolset remains
    finally:
        ledger.close()


def test_integrate_beat_over_a_complete_subtree_drops_all_mutating_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # The strongest over-submit guard (M3 §5): when EVERY child is already done with a passing DoD, the
    # delegated work is complete — the kernel's recommendation is `accept`, so the integrate harness is
    # materialized WITHOUT submit_task/assign_task. The manager literally cannot bolt on redundant work;
    # its only move is to accept. (A live gpt-class manager over-submits even when told to accept — brief
    # discipline is not enough, so the tools are withheld structurally.)
    from chorus.ledger import DodStatus, TaskStatus
    from chorus.outcomes import Verifier

    ledger = open_test_ledger()
    try:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
        )
        lead = _seed_delegation(ledger, child_status=TaskStatus.DONE)
        dod = ledger.dod.create(uid("kid"), Verifier.command("pytest", artifact_class="file"))
        ledger.dod.record_verdict(dod.id, DodStatus.PASSED, verdict={}, run_id=None)
        factory = _factory_mod.EmployeeHarnessFactory(
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            roles=RoleRegistry.from_plugins(default_roles()),
            work_root=tmp_path,
            ledger=ledger,
        )
        factory.materialize(lead, task_id=uid("goal"))
        names = {t.name for t in captured["registry"].list_tools()}
        assert "decompose" not in names
        assert (
            "submit_task" not in names and "assign_task" not in names
        )  # cannot over-submit a done subtree
        assert names == {
            "read_file",
            "read_offloaded",
            "team_read",
            "comment",  # coordination stays open — a comment mutates nothing (OM-3)
            "read_comments",
        }  # only reads + coordination remain before acceptance
    finally:
        ledger.close()


async def test_delegation_context_is_rehydrated_with_its_team(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    # A delegating role needs to name valid assignees: the factory appends the live workforce roster to
    # the manager's brief (which the overlays write onto every dream role).
    ledger = open_test_ledger()
    try:
        from chorus.workforce import Employee as _Emp

        lead = _seed_delegation(ledger)
        ledger.employees.create(
            _Emp(id="bob", name="Bob", role="backend_engineer", reports_to="moe")
        )
        ledger.employees.create(_Emp(id="eve", name="Eve", role="backend_engineer"))
        ledger.team_members.add(
            TeamMember(
                team_id=uid("team-goal"),
                employee_id="bob",
                source_manager_id="moe",
                membership_role=TeamMembershipRole.MEMBER,
            )
        )
        factory, captured = _factory(monkeypatch, tmp_path, ledger)
        mat = factory.materialize(lead, task_id=uid("goal"))
        generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text(
            "utf-8"
        )
        assert "ada (backend_engineer)" not in generator
        hook = next(
            item
            for item in captured["harness"].hooks
            if isinstance(item, VolatileBeatPacketHook)
        )
        packet = (
            await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "planner", "prompt": "work"})
        ).inject_context or ""
        assert "ada (backend_engineer)" in packet
        assert "bob (backend_engineer)" in packet
        assert "eve (engineer)" not in packet
        assert "moe" not in packet.split("Your reports")[1]
    finally:
        ledger.close()


async def test_corrective_child_inherits_failed_sibling_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Live T3 (2026-07-18): corrective children re-failed on findings they never saw. The
    beat brief must machine-inject the failed same-scope attempts' run outcomes and the
    evaluator notes recorded in the worktree, and authorize re-authoring implicated tests."""
    ledger = open_test_ledger()
    try:
        ic = Employee(id="bex", name="Bex", role="backend_engineer")
        ledger.employees.create(ic)
        parent = ledger.tasks.submit(Task(id=uid("root"), intent="deliver links"))
        failed = ledger.tasks.submit(
            Task(
                id=uid("attempt-1"),
                intent="build links.py",
                parent_id=parent.id,
                assignee_employee_id=ic.id,
                status=TaskStatus.REJECTED,
            )
        )
        corrective = ledger.tasks.submit(
            Task(
                id=uid("attempt-2"),
                intent="fix remaining review findings",
                parent_id=parent.id,
                assignee_employee_id=ic.id,
                status=TaskStatus.TODO,
            )
        )
        run_id = uid("failed-run")
        ledger.runs.create(
            Run(
                id=run_id,
                employee_id=ic.id,
                task_id=failed.id,
                status=RunStatus.FAILED,
            )
        )
        ledger.run_carryovers.append(
            RunCarryover(
                run_id=run_id,
                phase=LandedPhase.TERMINAL_FAIL,
                recovery_hint=RecoveryHint.REWORK,
                evaluator_notes=(
                    "base62 alphabet implementation contradicts the required 0-9,A-Z,a-z order",
                    "code_reviewer evidence does not carry the required claim",
                ),
            )
        )
        factory, captured = _factory(monkeypatch, tmp_path, ledger)
        mat = factory.materialize(ic, task_id=corrective.id)

        generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text("utf-8")
        assert "Inherited failure evidence" not in generator
        hook = [
            item
            for item in captured["harness"].hooks
            if isinstance(item, VolatileBeatPacketHook)
        ][-1]
        packet = (
            await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "generator", "prompt": "fix"})
        ).inject_context or ""
        assert "Corrective sibling findings" in packet
        assert failed.id in packet
        assert "contradicts the required 0-9,A-Z,a-z" in packet
        assert "code_reviewer evidence does not carry the required claim" in packet
    finally:
        ledger.close()


def test_first_attempt_child_gets_no_inheritance_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = open_test_ledger()
    try:
        ic = Employee(id="bex", name="Bex", role="backend_engineer")
        ledger.employees.create(ic)
        parent = ledger.tasks.submit(Task(id=uid("root"), intent="deliver links"))
        child = ledger.tasks.submit(
            Task(
                id=uid("attempt-1"),
                intent="build links.py",
                parent_id=parent.id,
                assignee_employee_id=ic.id,
                status=TaskStatus.TODO,
            )
        )
        factory, _ = _factory(monkeypatch, tmp_path, ledger)

        mat = factory.materialize(ic, task_id=child.id)

        generator = (mat.working_dir / ".harness" / "roles" / "generator.toml").read_text("utf-8")
        assert "Inherited failure evidence" not in generator
    finally:
        ledger.close()


@pytest.mark.parametrize(
    ("active", "can_lead", "expects_director_guidance"),
    ((True, True, True), (False, True, False), (True, False, False)),
)
def test_team_roster_uses_management_authority_to_identify_manager_reports(
    active: bool, can_lead: bool, expects_director_guidance: bool
) -> None:
    ledger = open_test_ledger()
    try:
        director = Employee(id="ceo", name="Casey", role="ceo")
        specialist_lead = Employee(
            id="backend-lead",
            name="Blair",
            role="backend_engineer",
            reports_to=director.id,
        )
        ledger.employees.create(director)
        ledger.employees.create(specialist_lead)
        ledger.management_profiles.upsert(
            ManagementProfile(
                employee_id=specialist_lead.id,
                granted_by_user_id="operator",
                active=active,
                can_lead=can_lead,
                max_delegation_depth=1,
                max_team_size=3,
                allowed_professions=("backend_engineer",),
            )
        )

        roster = _factory_mod._team_roster(ledger, exclude=director.id)

        assert ("You are a director" in roster) is expects_director_guidance
        assert ("manager reports (backend-lead)" in roster) is expects_director_guidance
    finally:
        ledger.close()


def test_management_profile_without_a_delegation_task_keeps_delivery_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    ledger = open_test_ledger()
    lead = _seed_delegation(ledger)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
        ledger=ledger,
    )
    factory.materialize(lead)
    names = {t.name for t in captured["registry"].list_tools()}
    assert not {"decompose", "submit_task", "assign_task"}.intersection(names)
    assert {"write_file", "bash", "git"} <= names
    ledger.close()


def test_runner_for_is_a_beat_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    runner = factory.runner_for(Employee(id="ada", name="Ada", role="backend_engineer"))
    assert isinstance(runner, BeatRunner)  # the scheduler dispatches through this


def test_unregistered_role_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ledger: Ledger
) -> None:
    factory, _ = _factory(monkeypatch, tmp_path, ledger)
    with pytest.raises(ValueError, match="not a registered role"):
        factory.materialize(Employee(id="x", name="X", role="ghost"))
