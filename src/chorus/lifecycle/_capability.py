"""CapabilityService — the manager's ledger-mutating capabilities (M3, spec 06 §4).

A manager beat's capability tools (``decompose`` for M3 Slice 1) reach the ledger through here. This is
the **dream-free seam**: the dream tool envelope unwraps to a plain method call on this service, so the
mutation logic is testable without a model in the loop.

It wraps the exact-once :func:`~chorus.lifecycle._decompose.decompose` lifecycle plus assignment with
the M3 idempotency rule — child ids are **deterministic per ``(parent, label)``**. A generator that
re-fires the same tool within a beat therefore produces the same children, and the underlying claim +
``create_child`` skip make the second pass a no-op.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from chorus.ledger._models import (
    ActivityVerb,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    Claim,
    DecisionRecord,
    DelegationContract,
    DelegationContractStatus,
    DodStatus,
    ExecutionMode,
    OriginKind,
    RejectedAlternative,
    Task,
    TaskStatus,
)
from chorus.lifecycle._audit import record_activity
from chorus.lifecycle._authority import (
    AuthorityIntersection,
    AuthorizationResult,
    EffectiveAuthority,
)
from chorus.lifecycle._coordination import assign_task
from chorus.lifecycle._decompose import (
    DEFAULT_REQUEST_DEPTH_CAP,
    ChildSpec,
    DepthCapped,
    decompose,
)
from chorus.lifecycle._team_policy import MissionTeamPolicy
from chorus.outcomes import DoDKind

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger


@dataclass(frozen=True)
class ChildPlan:
    """One child a manager wants to fan out: a stable ``label``, its ``intent``, an optional assignee,
    and ``depends_on`` sibling labels (edges within this wave, resolved to ids by the service)."""

    label: str
    intent: str
    assignee: str | None = None
    depends_on: tuple[str, ...] = ()
    execution_mode: ExecutionMode = ExecutionMode.DELIVERY
    can_subdelegate: bool = False
    replaces_task_id: str | None = None


@dataclass(frozen=True)
class DecomposeResult:
    """The outcome of a decompose call: the ``label → task_id`` map, or a fail-closed reason.

    Exactly one of the failure fields is set on a rejection (and ``child_ids`` is empty): ``depth_capped``
    when the fan-out would exceed the delegation depth cap, or ``unknown_assignees`` when a child names a
    report that is not a direct report employee. A clean fan-out leaves both empty and ``child_ids`` populated.
    """

    child_ids: dict[str, str] = field(default_factory=dict)
    depth_capped: bool = False
    unknown_assignees: tuple[str, ...] = ()
    reviewer_assignees: tuple[str, ...] = ()
    authority_denied: str | None = None


@dataclass(frozen=True)
class SubmitTaskResult:
    """The outcome of a manager submitting one follow-up child task."""

    child_id: str | None = None
    reviewer_assignees: tuple[str, ...] = ()
    depth_capped: bool = False
    unknown_assignees: tuple[str, ...] = ()
    authority_denied: str | None = None


@dataclass(frozen=True)
class AssignTaskResult:
    """The outcome of a manager re-routing one existing child task."""

    assigned: bool = False
    unknown_assignee: str | None = None
    not_child: bool = False
    terminal_or_missing: bool = False
    authority_denied: str | None = None


@dataclass(frozen=True)
class RecordVerdictResult:
    """The outcome of a reviewer rendering its approve/block verdict on a task's ``agent_review`` DoD.

    A clean record sets ``recorded`` with ``approved`` reflecting the decision. Exactly one fail-closed
    reason is set otherwise: ``not_reviewable`` when the task has no ``agent_review`` DoD to verdict, or
    ``self_review`` when the reviewer is the task's own author (a worker can't verify its own work)."""

    recorded: bool = False
    approved: bool = False
    not_reviewable: bool = False
    self_review: bool = False


# DoD kinds a Reviewer renders a verdict on (an objective ``command`` / a human approval are not).
_REVIEWER_GATED_KINDS = frozenset({DoDKind.AGENT_REVIEW, DoDKind.REVIEWED_BUILD})


def _child_id(parent_id: str, label: str) -> str:
    """A deterministic child id per ``(parent, label)`` so a re-fired decompose never duplicates."""
    digest = hashlib.sha1(f"{parent_id}::{label}".encode()).hexdigest()[:12]
    return f"task_{digest}"


def _decision_id(task_id: str, revision: str) -> str:
    """A deterministic decision id per ``(task, revision)`` so a re-fired record is idempotent."""
    digest = hashlib.sha1(f"{task_id}::{revision}".encode()).hexdigest()[:12]
    return f"dec_{digest}"


@dataclass(frozen=True)
class ClaimDraft:
    """The content of one cited claim as the PM supplies it — the service assigns the row ids."""

    text: str
    source_url: str
    confidence: float


@dataclass(frozen=True)
class DecisionOutcome:
    """The result of a ``record_decision`` call: the id, and whether this call wrote the rows.

    ``recorded`` is ``True`` when this call created the decision + claims; ``idempotent`` is ``True``
    when the ``(task, revision)`` decision already existed and the call was a no-op.

    ``record`` / ``claims`` carry the **canonical** recorded content — what this call wrote on a fresh
    record, or the **already-recorded** rows on an idempotent re-fire. The caller mirrors from these (not
    from its own input), so a second call with different content can never drift the mirror off the
    immutable ledger row.
    """

    decision_id: str
    recorded: bool
    idempotent: bool = False
    record: DecisionRecord | None = None
    claims: tuple[Claim, ...] = ()


class CapabilityService:
    """Ledger-mutating capabilities a manager beat invokes (``decompose`` for M3 Slice 1)."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def record_decision(
        self,
        *,
        task_id: str,
        revision: str,
        option: str,
        rationale: str,
        confidence: float,
        outcome_metric: str,
        revisit_trigger: str,
        rejected: Sequence[RejectedAlternative],
        claims: Sequence[ClaimDraft],
    ) -> DecisionOutcome:
        """Record a decision and its claims atomically, idempotent per ``(task_id, revision)`` (§10).

        Pure write: no confidence policy lives here — the grounding floor is enforced by the caller
        (the ``record_decision`` tool). A re-fired call with the same ``(task_id, revision)`` returns
        the existing id and writes nothing. The decision and every claim commit in one transaction, so
        a failure mid-write leaves no partial decision behind.
        """
        decision_id = _decision_id(task_id, revision)
        existing = self._ledger.decisions.get(decision_id)
        if existing is not None:
            # The record is immutable per beat: a re-fire is a no-op, and it reports the ALREADY-recorded
            # decision (not this call's input) so the caller mirrors the ledger, never the rejected input.
            recorded_claims = tuple(self._ledger.claims.for_decisions([decision_id]))
            return DecisionOutcome(
                decision_id,
                recorded=False,
                idempotent=True,
                record=existing,
                claims=recorded_claims,
            )
        record = DecisionRecord(
            id=decision_id,
            task_id=task_id,
            option=option,
            rationale=rationale,
            confidence=confidence,
            outcome_metric=outcome_metric,
            revisit_trigger=revisit_trigger,
            rejected_alternatives=tuple(rejected),
        )
        written_claims = tuple(
            Claim(
                id=f"{decision_id}-c{index}",
                decision_id=decision_id,
                text=claim.text,
                source_url=claim.source_url,
                confidence=claim.confidence,
            )
            for index, claim in enumerate(claims)
        )
        with self._ledger.transaction():
            self._ledger.decisions.create(record)
            for claim_row in written_claims:
                self._ledger.claims.create(claim_row)
        return DecisionOutcome(decision_id, recorded=True, record=record, claims=written_claims)

    def decompose(
        self,
        *,
        parent_id: str,
        revision: str,
        children: Sequence[ChildPlan],
        actor_employee_id: str | None = None,
    ) -> DecomposeResult:
        """Fan ``parent_id`` into ``children``, assign each, wire sibling deps — idempotent per ``revision``.

        Every child ``gates_parent`` (the parent waits on it via the M2 dependency gate). Returns
        :class:`DecomposeResult` with ``depth_capped=True`` and no children when the fan-out would exceed
        the delegation depth cap — the underlying lifecycle fails closed (parent set ``blocked``).

        ``revision`` is the manager's beat (``run_id``): the decomposition is recorded as the parent's
        accepted plan revision (the claim's exact-once key), so a re-fired tool resumes the same claim.
        """
        parent = self._ledger.tasks.get(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        if parent.execution_mode is not ExecutionMode.DELEGATION:
            return DecomposeResult(
                authority_denied="management mutations require a delegation task"
            )
        phase_denial = self._phase_denial(
            parent.id,
            DelegationContractStatus.DELEGATED,
            "decompose requires delegated contract phase",
        )
        if phase_denial is not None:
            return DecomposeResult(authority_denied=phase_denial)
        return self._mutate_children(
            parent=parent,
            revision=revision,
            children=children,
            actor_employee_id=actor_employee_id,
        )

    def _mutate_children(
        self,
        *,
        parent: Task,
        revision: str,
        children: Sequence[ChildPlan],
        actor_employee_id: str | None,
    ) -> DecomposeResult:
        reviewers = self._reviewer_assignees(children)
        if reviewers:
            return DecomposeResult(reviewer_assignees=reviewers)
        unknown = self._unknown_assignees(children, manager_id=parent.assignee_employee_id)
        if unknown:  # fail closed at the boundary — a bad report id never half-applies a fan-out
            return DecomposeResult(unknown_assignees=unknown)

        decision = self._authorize_wave(parent, children, actor_employee_id)
        if not decision.authorized:
            return DecomposeResult(authority_denied=decision.reason)
        authority = decision.effective
        if authority is None:
            raise RuntimeError("authorized delegation wave has no effective limits")

        ids = {child.label: _child_id(parent.id, child.label) for child in children}
        request_fingerprint = hashlib.sha256(
            json.dumps(
                [
                    {
                        "assignee": child.assignee,
                        "can_subdelegate": child.can_subdelegate,
                        "depends_on": list(child.depends_on),
                        "execution_mode": child.execution_mode.value,
                        "intent": child.intent,
                        "replaces_task_id": child.replaces_task_id,
                        "task_id": ids[child.label],
                    }
                    for child in children
                ],
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        accepted_plan_revision_id = self._ensure_plan_revision(parent.id, revision)
        existing_claim = self._ledger.decomposition_claims.by_source_revision(
            parent.id, accepted_plan_revision_id
        )
        if existing_claim is not None and existing_claim.request_fingerprint != request_fingerprint:
            return DecomposeResult(
                authority_denied="this manager beat already committed a different child wave"
            )
        contract = self._ledger.delegation_contracts.get(parent.id)
        if contract is None:
            raise RuntimeError("authorized delegation task is missing its contract")
        existing_child_ids = {child.id for child in self._ledger.tasks.children(parent.id)}
        new_child_count = sum(child_id not in existing_child_ids for child_id in ids.values())
        if (
            contract.max_direct_children is not None
            and len(existing_child_ids) + new_child_count > contract.max_direct_children
        ):
            return DecomposeResult(
                authority_denied="delegation contract direct child limit exceeded"
            )
        team_policy = MissionTeamPolicy(self._ledger)
        child_team_ids: dict[str, str | None] = {}
        with self._ledger.transaction():
            if authority is not None:
                if parent.team_id is None or parent.goal_id is None:
                    raise RuntimeError("authorized delegation task is missing Team or goal")
                for child in children:
                    if child.assignee is not None:
                        team_policy.add_member(
                            parent.team_id,
                            child.assignee,
                            can_subdelegate=child.can_subdelegate,
                        )
                    if child.execution_mode is ExecutionMode.DELEGATION:
                        lead = self._ledger.employees.get(child.assignee or "")
                        if lead is None:
                            raise RuntimeError("authorized delegation child has no lead")
                        nested = team_policy.create_for_delegation(
                            lead,
                            goal_id=parent.goal_id,
                            parent_team_id=parent.team_id,
                            delegation_task_id=ids[child.label],
                        )
                        child_team_ids[child.label] = nested.id
                    else:
                        child_team_ids[child.label] = parent.team_id

            specs = [
                ChildSpec(
                    task=Task(
                        id=ids[child.label],
                        intent=child.intent,
                        status=TaskStatus.TODO,
                        execution_mode=child.execution_mode,
                        team_id=child_team_ids.get(child.label),
                        assignee_employee_id=child.assignee,
                        origin_kind=OriginKind.DECOMPOSITION,
                        origin_id=parent.id,
                        origin_fingerprint=child.label,
                    ),
                    gates_parent=True,
                )
                for child in children
            ]
            decompose_args: dict[str, object] = {}
            if authority is not None:
                decompose_args["request_depth_cap"] = min(
                    DEFAULT_REQUEST_DEPTH_CAP,
                    parent.request_depth + authority.max_depth,
                )
            outcome = decompose(
                self._ledger,
                source_task_id=parent.id,
                accepted_plan_revision_id=accepted_plan_revision_id,
                owner_run_id=self._owner_run_id(revision),
                children=specs,
                request_fingerprint=request_fingerprint,
                **decompose_args,  # type: ignore[arg-type]
            )
            if isinstance(outcome, DepthCapped):
                return DecomposeResult(depth_capped=True)

            for child in children:
                if child.replaces_task_id is not None:
                    self._ledger.dependencies.remove(parent.id, child.replaces_task_id)
                    self._ledger.dependencies.add(parent.id, ids[child.label])

            for child in children:
                if child.assignee is not None:
                    assign_task(self._ledger, ids[child.label], child.assignee)
                for blocker_label in child.depends_on:
                    self._ledger.dependencies.add(ids[child.label], ids[blocker_label])
                if authority is not None and child.execution_mode is ExecutionMode.DELEGATION:
                    self._create_nested_contract(
                        parent=parent,
                        child=child,
                        child_id=ids[child.label],
                        team_id=child_team_ids[child.label],
                        authority=authority,
                        actor_employee_id=actor_employee_id,
                    )
                    team_policy.activate(child_team_ids[child.label] or "")
        return DecomposeResult(child_ids=ids)

    def _authorize_wave(
        self,
        parent: Task,
        children: Sequence[ChildPlan],
        actor_employee_id: str | None,
    ) -> AuthorizationResult:
        actor = self._ledger.employees.get(actor_employee_id or "")
        if actor is None:
            return AuthorizationResult(False, reason="actor is not the delegation contract lead")
        authority = AuthorityIntersection(self._ledger)
        decision = authority.check(actor, parent)
        if not decision.authorized:
            return decision
        for child in children:
            if child.execution_mode is ExecutionMode.DELEGATION and child.assignee is None:
                return AuthorizationResult(False, reason="delegation child requires a lead")
            target = self._ledger.employees.get(child.assignee or "")
            target_decision = authority.check(
                actor,
                parent,
                target,
                requested_mode=child.execution_mode,
            )
            if not target_decision.authorized:
                return target_decision
            if child.execution_mode is ExecutionMode.DELEGATION and not child.can_subdelegate:
                return AuthorizationResult(
                    False,
                    reason="nested delegation requires an explicit Team grant",
                )
        if parent.team_id is None or decision.effective is None:
            return AuthorizationResult(False, reason="active delegation Team is invalid")
        active_members = {
            member.employee_id for member in self._ledger.team_members.members_of(parent.team_id)
        }
        proposed_members = active_members | {
            child.assignee for child in children if child.assignee is not None
        }
        if len(proposed_members) > decision.effective.max_team_size:
            return AuthorizationResult(False, reason="Team size limit exceeded")
        return decision

    def _create_nested_contract(
        self,
        *,
        parent: Task,
        child: ChildPlan,
        child_id: str,
        team_id: str | None,
        authority: EffectiveAuthority,
        actor_employee_id: str | None,
    ) -> None:
        if self._ledger.delegation_contracts.get(child_id) is not None:
            return
        lead_profile = self._ledger.management_profiles.get(child.assignee or "")
        if lead_profile is None or team_id is None:
            raise RuntimeError("authorized nested delegation is missing profile or Team")
        spend_limits = [
            limit
            for limit in (authority.spend_limit_cents, lead_profile.spend_limit_cents)
            if limit is not None
        ]
        contract = DelegationContract(
            task_id=child_id,
            team_id=team_id,
            lead_employee_id=child.assignee or "",
            management_profile_version=lead_profile.version,
            parent_contract_task_id=parent.id,
            can_subdelegate=authority.can_subdelegate and lead_profile.can_subdelegate,
            max_depth=min(max(authority.max_depth - 1, 0), lead_profile.max_delegation_depth),
            max_team_size=min(authority.max_team_size, lead_profile.max_team_size),
            spend_limit_cents=min(spend_limits) if spend_limits else None,
            objective_rubric=child.intent,
            status=DelegationContractStatus.DELEGATED,
        )
        self._ledger.delegation_contracts.create(contract)
        record_activity(
            self._ledger,
            verb=ActivityVerb.DELEGATION_CREATED,
            subject_kind="delegation_contract",
            subject_id=child_id,
            actor_employee_id=actor_employee_id,
        )

    def submit_one(
        self,
        *,
        parent_id: str,
        revision: str,
        child: ChildPlan,
        actor_employee_id: str | None = None,
    ) -> SubmitTaskResult:
        """Submit one incremental child task during an integrate beat.

        This is the manager's bounded "create one follow-up" move. It uses the same exact-once
        decomposition claim machinery as :meth:`decompose`, but with a single child and a revision
        unique to the current manager beat/action.
        """
        parent = self._ledger.tasks.get(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        if parent.execution_mode is not ExecutionMode.DELEGATION:
            outcome = DecomposeResult(
                authority_denied="management mutations require a delegation task"
            )
        else:
            phase_denial = self._phase_denial(
                parent.id,
                DelegationContractStatus.INTEGRATING,
                "corrective mutation requires integrating contract phase",
            )
            outcome = (
                DecomposeResult(authority_denied=phase_denial)
                if phase_denial is not None
                else self._replacement_denial(parent, child)
                or self._mutate_children(
                    parent=parent,
                    revision=revision,
                    children=(child,),
                    actor_employee_id=actor_employee_id,
                )
            )
        return SubmitTaskResult(
            child_id=outcome.child_ids.get(child.label),
            reviewer_assignees=outcome.reviewer_assignees,
            depth_capped=outcome.depth_capped,
            unknown_assignees=outcome.unknown_assignees,
            authority_denied=outcome.authority_denied,
        )

    def _replacement_denial(self, parent: Task, child: ChildPlan) -> DecomposeResult | None:
        replaced_id = child.replaces_task_id
        if replaced_id is None:
            for blocker_id in self._ledger.dependencies.blockers(parent.id):
                blocker = self._ledger.tasks.get(blocker_id)
                if blocker is not None and blocker.status in {
                    TaskStatus.REJECTED,
                    TaskStatus.CANCELLED,
                }:
                    return DecomposeResult(
                        authority_denied=(
                            f"failed direct child {blocker_id} must be named in replaces_task_id"
                        )
                    )
            return None
        replaced = self._ledger.tasks.get(replaced_id)
        correction_id = _child_id(parent.id, child.label)
        blockers = set(self._ledger.dependencies.blockers(parent.id))
        if correction_id in blockers and replaced_id not in blockers:
            return None
        if replaced is None or replaced.parent_id != parent.id:
            return DecomposeResult(
                authority_denied="corrective replacement must target a direct child"
            )
        if replaced.status not in {TaskStatus.REJECTED, TaskStatus.CANCELLED}:
            return DecomposeResult(
                authority_denied="corrective replacement target must have failed"
            )
        if replaced_id not in blockers:
            return DecomposeResult(
                authority_denied="corrective replacement target must gate the parent"
            )
        return None

    def reassign(
        self, *, parent_id: str, task_id: str, assignee: str, assigned_by: str | None = None
    ) -> AssignTaskResult:
        """Route one direct child of ``parent_id`` to one of the parent's direct reports."""
        parent = self._ledger.tasks.get(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        if parent.execution_mode is not ExecutionMode.DELEGATION:
            return AssignTaskResult(
                authority_denied="management mutations require a delegation task"
            )
        phase_denial = self._phase_denial(
            parent.id,
            DelegationContractStatus.INTEGRATING,
            "corrective mutation requires integrating contract phase",
        )
        if phase_denial is not None:
            return AssignTaskResult(authority_denied=phase_denial)
        if not self._is_direct_report(assignee, manager_id=parent.assignee_employee_id):
            return AssignTaskResult(unknown_assignee=assignee)
        task = self._ledger.tasks.get(task_id)
        if task is None:
            return AssignTaskResult(terminal_or_missing=True)
        if task.parent_id != parent_id:
            return AssignTaskResult(not_child=True)
        decision = self._authorize_wave(
            parent,
            (
                ChildPlan(
                    label="reassign",
                    intent=task.intent,
                    assignee=assignee,
                    execution_mode=task.execution_mode,
                ),
            ),
            assigned_by,
        )
        if not decision.authorized:
            return AssignTaskResult(authority_denied=decision.reason)
        if task.execution_mode is ExecutionMode.DELEGATION:
            return AssignTaskResult(
                authority_denied="delegation lead changes require governed reorganization"
            )
        if parent.team_id is None:
            return AssignTaskResult(authority_denied="active delegation Team is invalid")
        with self._ledger.transaction():
            MissionTeamPolicy(self._ledger).add_member(parent.team_id, assignee)
            if assign_task(self._ledger, task_id, assignee, assigned_by=assigned_by) is None:
                return AssignTaskResult(terminal_or_missing=True)
        return AssignTaskResult(assigned=True)

    def _phase_denial(
        self,
        task_id: str,
        required: DelegationContractStatus,
        reason: str,
    ) -> str | None:
        contract = self._ledger.delegation_contracts.get(task_id)
        if contract is None or contract.status is not required:
            return reason
        return None

    def record_verdict(
        self,
        *,
        task_id: str,
        run_id: str,
        reviewer_id: str,
        approve: bool,
        feedback: str,
        verify_command: str = "",
    ) -> RecordVerdictResult:
        """Record a reviewer's verdict on a task's reviewer-gated DoD (approve→PASSED, block→FAILED).

        The verdict IS the DoD's verdict — it does not itself transition the task. The kernel reads the
        recorded DoD status after the reviewer beat and lands (approve) or routes the block. For a
        ``reviewed_build`` DoD the reviewer also reports ``verify_command`` (the project's verify command
        the kernel then runs); a PASSED here means "quality approved", with the objective run still to
        come. Fails closed on a non reviewer-gated DoD or a reviewer verifying its own work."""
        task = self._ledger.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        dod = self._ledger.dod.get_for_task(task_id)
        if dod is None or DoDKind(dod.kind) not in _REVIEWER_GATED_KINDS:
            return RecordVerdictResult(not_reviewable=True)
        run = self._ledger.runs.get(run_id)
        system_principal_id = (
            run.system_principal_id
            if run is not None and run.task_id == task_id and run.principal_kind == "system"
            else None
        )
        canonical_reviewer_id = system_principal_id or reviewer_id
        if system_principal_id is None and canonical_reviewer_id == task.assignee_employee_id:
            return RecordVerdictResult(self_review=True)
        status = DodStatus.PASSED if approve else DodStatus.FAILED
        verdict: dict[str, object] = {
            "approve": approve,
            "feedback": feedback,
            "reviewer": canonical_reviewer_id,
        }
        if verify_command:  # only a reviewed_build carries a command for the kernel to run
            verdict["verify_command"] = verify_command
        self._ledger.dod.record_verdict(dod.id, status, verdict=verdict, run_id=run_id)
        record_activity(
            self._ledger,
            verb=ActivityVerb.REVIEW_VERDICT,
            subject_id=task_id,
            actor_employee_id=None if system_principal_id is not None else canonical_reviewer_id,
            actor_system_principal_id=system_principal_id,
            payload={"approve": approve, "feedback": feedback},
        )
        return RecordVerdictResult(recorded=True, approved=approve)

    def _unknown_assignees(
        self, children: Sequence[ChildPlan], *, manager_id: str | None
    ) -> tuple[str, ...]:
        """Assignees named by ``children`` that are not direct reports — ordered and deduplicated."""
        seen: dict[str, None] = {}
        for child in children:
            if child.assignee is None:
                continue
            if not self._is_direct_report(child.assignee, manager_id=manager_id):
                seen.setdefault(child.assignee, None)
        return tuple(seen)

    def _reviewer_assignees(self, children: Sequence[ChildPlan]) -> tuple[str, ...]:
        """Assignees that are reviewers — ordered and deduplicated.

        A reviewer *reviews* (the kernel auto-dispatches it for a reviewer-gated DoD); it never *owns*
        deliverable work — its role is read-only with a human-approval DoD, so a deliverable routed to
        one would strand. Fail closed so the manager reassigns the work to an engineer."""
        seen: dict[str, None] = {}
        for child in children:
            if child.assignee is None:
                continue
            employee = self._ledger.employees.get(child.assignee)
            if employee is not None and employee.role == "reviewer":
                seen.setdefault(child.assignee, None)
        return tuple(seen)

    def _is_direct_report(self, employee_id: str, *, manager_id: str | None) -> bool:
        employee = self._ledger.employees.get(employee_id)
        return manager_id is not None and employee is not None and employee.reports_to == manager_id

    def _ensure_plan_revision(self, parent_id: str, revision: str) -> str:
        """Record (once per beat) the parent's accepted decomposition plan; return its revision id.

        Idempotent: keyed on ``revision`` (the run_id), so a re-fired tool finds the existing revision
        and skips creation. The artifact anchors the claim's lineage guard to the parent task.
        """
        plan_revision_id = f"planrev_{revision}"
        if self._ledger.artifact_revisions.get(plan_revision_id) is not None:
            return plan_revision_id
        artifact_id = f"plan_{parent_id}__{revision}"
        self._ledger.artifacts.create(
            Artifact(id=artifact_id, task_id=parent_id, type=ArtifactType.DOC)
        )
        self._ledger.artifact_revisions.record(
            ArtifactRevision(
                id=plan_revision_id,
                artifact_id=artifact_id,
                resource_ref={"decompose": revision},
            )
        )
        return plan_revision_id

    def _owner_run_id(self, revision: str) -> str | None:
        """Use ``revision`` as owner only when it is a real run id; tests may use synthetic revisions."""
        return revision if self._ledger.runs.get(revision) is not None else None


__all__ = [
    "AssignTaskResult",
    "CapabilityService",
    "ChildPlan",
    "DecomposeResult",
    "SubmitTaskResult",
]
