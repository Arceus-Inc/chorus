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
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from chorus.ids import derive_id
from chorus.ledger._models import (
    ActivityVerb,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    Claim,
    DecisionRecord,
    DelegationContract,
    DelegationContractStatus,
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
from chorus.lifecycle._file_scope import (
    BlockerScope,
    FileScopeViolation,
    ProposedBlockerScope,
    validate_file_scope,
)
from chorus.lifecycle._outcome_capability import OutcomeMismatch, outcome_mismatches
from chorus.lifecycle._team_policy import MissionTeamPolicy
from chorus.outcomes import (
    DeliverableKind,
    OutcomeKind,
    classify_deliverable,
    native_kind_for_role,
)
from chorus.workforce import Employee, EmployeeStatus, LedgerWorkforce

if TYPE_CHECKING:
    from chorus.ledger import Ledger
    from chorus.roles import RoleRegistry


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
    # The deliverable the child is expected to land. When set, the service refuses to assign it to a
    # role that produces a different kind (a ``pr`` child routed to a ``doc`` pm strands). ``None``
    # skips the check so internal callers and undeclared tool args stay fail-open.
    outcome_kind: OutcomeKind | None = None
    files_to_touch: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityReroute:
    """One audited correction of a mis-crafted DELIVERY child's assignee."""

    label: str
    from_assignee: str
    to_assignee: str


@dataclass(frozen=True)
class RoutedChildWave:
    """A decompose/submit wave after optional craft-matched reassignment."""

    children: tuple[ChildPlan, ...]
    reroutes: tuple[CapabilityReroute, ...] = ()


@dataclass(frozen=True)
class ManagerAreaViolation:
    """Director-only decomposition shape that must be enforced before any fan-out mutation."""

    manager_report_ids: tuple[str, ...]
    assigned_manager_report_ids: tuple[str, ...]
    invalid_child_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecomposeResult:
    """The outcome of a decompose call: the ``label → task_id`` map, or a fail-closed reason.

    Exactly one of the failure fields is set on a rejection (and ``child_ids`` is empty): ``depth_capped``
    when the fan-out would exceed the delegation depth cap, ``unknown_assignees`` when a child names a
    report that is not a direct report, ``manager_area_violation`` when a director wave does not map
    one-to-one onto invokable manager reports, ``outcome_mismatches`` when a child's declared outcome
    can't be produced by its assignee's role, ``authority_denied`` for a contract/profession refusal,
    or ``scope_violations`` when declared file scopes are empty, out-of-parent, or overlapping.
    A clean fan-out leaves the failure fields empty and ``child_ids`` populated.
    """

    child_ids: dict[str, str] = field(default_factory=dict)
    depth_capped: bool = False
    unknown_assignees: tuple[str, ...] = ()
    reviewer_assignees: tuple[str, ...] = ()
    manager_area_violation: ManagerAreaViolation | None = None
    authority_denied: str | None = None
    outcome_mismatches: tuple[OutcomeMismatch, ...] = ()
    scope_violations: tuple[FileScopeViolation, ...] = ()


@dataclass(frozen=True)
class SubmitTaskResult:
    """The outcome of a manager submitting one follow-up child task."""

    child_id: str | None = None
    reviewer_assignees: tuple[str, ...] = ()
    depth_capped: bool = False
    unknown_assignees: tuple[str, ...] = ()
    authority_denied: str | None = None
    outcome_mismatches: tuple[OutcomeMismatch, ...] = ()
    scope_violations: tuple[FileScopeViolation, ...] = ()


@dataclass(frozen=True)
class AssignTaskResult:
    """The outcome of a manager re-routing one existing child task."""

    assigned: bool = False
    unknown_assignee: str | None = None
    not_child: bool = False
    terminal_or_missing: bool = False
    authority_denied: str | None = None


def _child_id(parent_id: str, label: str) -> str:
    """A deterministic child id per ``(parent, label)`` so a re-fired decompose never duplicates."""
    return derive_id("child", parent_id, label)


def _decision_id(task_id: str, revision: str) -> str:
    """A deterministic decision id per ``(task, revision)`` so a re-fired record is idempotent."""
    return derive_id("decision", task_id, revision)


def _request_fingerprint(
    children: Sequence[ChildPlan],
    ids: dict[str, str],
    *,
    files_to_touch_by_id: dict[str, tuple[str, ...]],
) -> str:
    """Canonicalize the exact-once comparison surface without changing mutation order.

    Child order, ``depends_on`` ordering, and ``files_to_touch`` ordering are semantic-free, so
    retries that only reshuffle them must resume the same wave instead of tripping the "different
    child wave" guard. Moving a path from one child to another remains a different wave.
    """
    payload = [
        {
            "assignee": child.assignee,
            "can_subdelegate": child.can_subdelegate,
            "depends_on": sorted(child.depends_on),
            "execution_mode": child.execution_mode.value,
            "intent": child.intent,
            "outcome_kind": None if child.outcome_kind is None else child.outcome_kind.value,
            "replaces_task_id": child.replaces_task_id,
            "files_to_touch": sorted(files_to_touch_by_id[ids[child.label]]),
            "task_id": ids[child.label],
        }
        for child in sorted(children, key=lambda child: child.label)
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


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

    def __init__(self, ledger: Ledger, *, roles: RoleRegistry | None = None) -> None:
        self._ledger = ledger
        # The role registry powers capability-matched routing (decompose/submit_one). Optional so the
        # non-decompose callers (record_decision, reassign) keep working unchanged; routing is simply
        # inert without it.
        self._roles = roles

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
                id=derive_id("claim", decision_id, str(index)),
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
            enforce_manager_area_fanout=True,
        )

    def _mutate_children(
        self,
        *,
        parent: Task,
        revision: str,
        children: Sequence[ChildPlan],
        actor_employee_id: str | None,
        enforce_manager_area_fanout: bool = False,
    ) -> DecomposeResult:
        # Compose order is load-bearing: DELIVERY craft reroute (skips declared outcome_kind),
        # then director manager-area (decompose-only), then reviewer / unknown / outcome mismatch /
        # team-grant / authorization, then file-scope. Routing is DELIVERY-only (a no-op on director
        # DELEGATION waves) and must not run after those gates or it would rewrite an already-authorized
        # wave. Post-route gates still run on the rewritten assignees. File-scope runs after those
        # identity/capability gates and before any mutation so empty, out-of-parent, or overlapping
        # claims never write children.
        routed = self._capability_route(children, manager_id=parent.assignee_employee_id)
        children = routed.children
        reroutes = routed.reroutes
        manager_area_violation = (
            self._manager_area_violation(parent, children) if enforce_manager_area_fanout else None
        )
        if manager_area_violation is not None:
            return DecomposeResult(manager_area_violation=manager_area_violation)
        reviewers = self._reviewer_assignees(children)
        if reviewers:
            return DecomposeResult(reviewer_assignees=reviewers)
        unknown = self._unknown_assignees(children, manager_id=parent.assignee_employee_id)
        if unknown:  # fail closed at the boundary — a bad report id never half-applies a fan-out
            return DecomposeResult(unknown_assignees=unknown)
        mismatches = self._outcome_mismatches(children)
        if mismatches:
            return DecomposeResult(outcome_mismatches=mismatches)
        team_grant_denial = self._team_grant_denial(parent, children)
        if team_grant_denial is not None:
            return DecomposeResult(authority_denied=team_grant_denial)

        decision = self._authorize_wave(parent, children, actor_employee_id)
        if not decision.authorized:
            return DecomposeResult(authority_denied=decision.reason)
        authority = decision.effective
        if authority is None:
            raise RuntimeError("authorized delegation wave has no effective limits")

        ids = {child.label: _child_id(parent.id, child.label) for child in children}
        current_blockers = self._current_blocker_scopes(parent.id)
        scoped_plan = bool(parent.files_to_touch) or any(
            blocker.files_to_touch for blocker in current_blockers
        )
        validation = validate_file_scope(
            parent_files_to_touch=parent.files_to_touch,
            current_blockers=current_blockers,
            proposed_blockers=tuple(
                ProposedBlockerScope(
                    task_id=ids[child.label],
                    files_to_touch=child.files_to_touch,
                    replaces_task_id=child.replaces_task_id,
                )
                for child in children
            ),
            require_current_scope=scoped_plan,
            require_proposed_scope=scoped_plan,
        )
        if not validation.valid:
            return DecomposeResult(scope_violations=validation.violations)
        normalized_scope_by_id = {
            child.task_id: child.files_to_touch for child in validation.proposed_blockers
        }
        request_fingerprint = _request_fingerprint(
            children, ids, files_to_touch_by_id=normalized_scope_by_id
        )
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
        decompose_args: dict[str, object] = {}
        request_depth_cap = DEFAULT_REQUEST_DEPTH_CAP
        if authority is not None:
            request_depth_cap = min(
                DEFAULT_REQUEST_DEPTH_CAP,
                parent.request_depth + authority.max_depth,
            )
            decompose_args["request_depth_cap"] = request_depth_cap
        with self._ledger.transaction():
            # The kernel depth cap is deterministic from the parent alone — mirror decompose()'s
            # own check BEFORE any Team mutation. transaction() commits on an early return, so a
            # refusal here must commit ONLY decompose()'s fail-closed card (source blocked +
            # recovery action), never a roster/Team write for a wave that was refused.
            if parent.request_depth + 1 > request_depth_cap:
                outcome = decompose(
                    self._ledger,
                    source_task_id=parent.id,
                    accepted_plan_revision_id=accepted_plan_revision_id,
                    owner_run_id=self._owner_run_id(revision),
                    children=(),
                    request_fingerprint=request_fingerprint,
                    **decompose_args,  # type: ignore[arg-type]
                )
                if not isinstance(outcome, DepthCapped):  # pragma: no cover — condition mirror
                    raise RuntimeError("depth precheck disagreed with decompose()")
                return DecomposeResult(depth_capped=True)
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
                        files_to_touch=normalized_scope_by_id[ids[child.label]],
                    ),
                    gates_parent=True,
                )
                for child in children
            ]
            outcome = decompose(
                self._ledger,
                source_task_id=parent.id,
                accepted_plan_revision_id=accepted_plan_revision_id,
                owner_run_id=self._owner_run_id(revision),
                children=specs,
                request_fingerprint=request_fingerprint,
                **decompose_args,  # type: ignore[arg-type]
            )
            if isinstance(outcome, DepthCapped):  # pragma: no cover — precheck above prevents this
                # Raising (not returning) rolls the Team mutations back if the precheck and
                # decompose() ever drift apart — a refusal must never commit partial writes.
                raise RuntimeError("decompose depth-capped after Team mutations")

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
            if reroutes:
                # Audit the capability re-routes atomically with the children they retargeted, so the
                # cockpit/report can see the manager's pick was corrected and to whom.
                record_activity(
                    self._ledger,
                    verb=ActivityVerb.ASSIGNED,
                    subject_id=parent.id,
                    actor_employee_id=parent.assignee_employee_id,
                    payload={
                        "capability_reroute": [
                            {
                                "label": reroute.label,
                                "from": reroute.from_assignee,
                                "to": reroute.to_assignee,
                            }
                            for reroute in reroutes
                        ]
                    },
                )
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

    def _manager_area_violation(
        self, parent: Task, children: Sequence[ChildPlan]
    ) -> ManagerAreaViolation | None:
        manager_report_ids = self._manager_report_ids(parent)
        if not manager_report_ids:
            return None
        manager_report_set = frozenset(manager_report_ids)
        assigned_manager_report_ids: list[str] = []
        invalid_child_labels: list[str] = []
        for child in children:
            assignee = child.assignee
            if (
                assignee is None
                or assignee not in manager_report_set
                or child.execution_mode is not ExecutionMode.DELEGATION
                or not child.can_subdelegate
            ):
                invalid_child_labels.append(child.label)
                continue
            assigned_manager_report_ids.append(assignee)
        if (
            len(children) == len(manager_report_ids)
            and not invalid_child_labels
            and len(set(assigned_manager_report_ids)) == len(manager_report_ids)
            and frozenset(assigned_manager_report_ids) == manager_report_set
        ):
            return None
        return ManagerAreaViolation(
            manager_report_ids=manager_report_ids,
            assigned_manager_report_ids=tuple(assigned_manager_report_ids),
            invalid_child_labels=tuple(invalid_child_labels),
        )

    def _team_grant_denial(self, parent: Task, children: Sequence[ChildPlan]) -> str | None:
        if parent.team_id is None:
            return None
        for child in children:
            if child.assignee is None:
                continue
            member = self._ledger.team_members.get(parent.team_id, child.assignee)
            if (
                member is not None
                and member.left_at is None
                and member.can_subdelegate != child.can_subdelegate
            ):
                return (
                    f"existing Team membership for {child.assignee!r} has a different "
                    "subdelegation grant; use governed reorganization"
                )
        return None

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
            outcome_mismatches=outcome.outcome_mismatches,
            scope_violations=outcome.scope_violations,
        )

    def _replacement_denial(self, parent: Task, child: ChildPlan) -> DecomposeResult | None:
        correction_id = _child_id(parent.id, child.label)
        existing = self._ledger.tasks.get(correction_id)
        if existing is not None:
            # Live T3 finding (2026-07-18): the lead reused the failed child's label and the
            # deterministic (parent, label) id collided as a raw duplicate-key error. Refuse
            # typed, with the fix, before the insert.
            return DecomposeResult(
                authority_denied=(
                    f"label {child.label!r} already names an existing child "
                    f"({correction_id}); pick a NEW label for the corrective task"
                )
            )
        replaced_id = child.replaces_task_id
        if replaced_id is None:
            failed = [
                blocker_id
                for blocker_id in self._ledger.dependencies.blockers(parent.id)
                if (blocker := self._ledger.tasks.get(blocker_id)) is not None
                and blocker.status in {TaskStatus.REJECTED, TaskStatus.CANCELLED}
            ]
            if failed:
                # Live T3 finding (2026-07-18): a lead burned every integrate iteration on this
                # refusal because it never learned the exact corrective call. Name every failed
                # child and the exact field so ONE refusal is enough to self-correct.
                listed = ", ".join(failed)
                return DecomposeResult(
                    authority_denied=(
                        f"failed direct child {failed[0]} must be named in replaces_task_id. "
                        f"Correction: re-call submit_task with a NEW label (child ids derive "
                        f"from the label, so reusing the failed child's label collides), the "
                        f'same intent/assignee, plus replaces_task_id="{failed[0]}" — one '
                        f"corrective task per failed child. Failed children gating this task: "
                        f"{listed}"
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
            # Assign FIRST: a terminal/missing task refuses before anything is written, so the
            # early return (which commits) commits nothing — the roster only ever gains the
            # member alongside a real assignment.
            if assign_task(self._ledger, task_id, assignee, assigned_by=assigned_by) is None:
                return AssignTaskResult(terminal_or_missing=True)
            MissionTeamPolicy(self._ledger).add_member(parent.team_id, assignee)
        return AssignTaskResult(assigned=True)

    def _current_blocker_scopes(self, parent_id: str) -> tuple[BlockerScope, ...]:
        blockers: list[BlockerScope] = []
        for blocker_id in self._ledger.dependencies.blockers(parent_id):
            blocker = self._ledger.tasks.get(blocker_id)
            if blocker is None or blocker.parent_id != parent_id:
                continue
            blockers.append(BlockerScope(task_id=blocker.id, files_to_touch=blocker.files_to_touch))
        return tuple(blockers)

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

    def _capability_route(
        self, children: Sequence[ChildPlan], *, manager_id: str | None
    ) -> RoutedChildWave:
        """Re-route a strongly mis-crafted DELIVERY child to a better-matched free report.

        F1 already judges a cross-assigned deliverable by its OWN standard, so correct work is never
        rejected for the wrong rubric; this closes the other half — don't route craft work to the
        wrong craft when a better-matched report is free, so the pod doesn't burn a beat producing a
        rejectable deliverable. Deterministic and derived from the role registry (each role's native
        kind is read from its own DoD — no task→role table). Inert without a registry, so the
        non-decompose callers are unaffected.

        An unauthorized or non-report original assignee is never rewritten — that would launder a
        fail-closed unknown/authority denial into a valid assignment. A child with a declared
        ``outcome_kind`` is also left as named so the outcome-capability check validates the
        manager's pair. Post-route manager-area (decompose-only), reviewer, unknown, outcome, and
        authorize gates still run on the (possibly rewritten) wave.
        """
        if self._roles is None or manager_id is None:
            return RoutedChildWave(children=tuple(children))
        profile = self._ledger.management_profiles.get(manager_id)
        allowed = frozenset(profile.allowed_professions) if profile is not None else frozenset()
        reports = [
            employee
            for employee in self._ledger.employees.list()
            if employee.reports_to == manager_id
            and employee.status
            not in (
                EmployeeStatus.TERMINATED,
                EmployeeStatus.PAUSED,
                EmployeeStatus.PENDING,
            )
            and employee.role != "reviewer"
            and (not allowed or employee.role in allowed)
        ]
        routed: list[ChildPlan] = []
        trail: list[CapabilityReroute] = []
        for child in children:
            target = self._better_matched_report(child, reports)
            if target is None:
                routed.append(child)
                continue
            trail.append(
                CapabilityReroute(
                    label=child.label,
                    from_assignee=child.assignee or "",
                    to_assignee=target,
                )
            )
            routed.append(replace(child, assignee=target))
        return RoutedChildWave(children=tuple(routed), reroutes=tuple(trail))

    def _better_matched_report(self, child: ChildPlan, reports: Sequence[Employee]) -> str | None:
        """The id of a strictly-better-matched report for a mis-crafted DELIVERY child.

        ``None`` (keep the manager's pick) unless ALL hold: the child is DELIVERY craft work with no
        declared ``outcome_kind``; its intent carries an unambiguous deliverable cue (not
        ROLE_DEFAULT); the current assignee is an eligible direct report whose craft is a *different*
        concrete kind (a generalist whose native kind is ROLE_DEFAULT is never "wrong", and a
        non-report is never rewritten); and a different report actually produces that kind. Among
        matches the lowest employee id wins — load is ignored so the decompose claim fingerprint is
        stable across in-beat retries. Canonical / ambiguous work, declared-kind assignments, and
        pods that lack the ideal craft are left exactly as asked.
        """
        roles = self._roles
        if (
            roles is None
            or child.execution_mode is not ExecutionMode.DELIVERY
            or child.assignee is None
            or child.outcome_kind is not None
        ):
            return None
        task_kind = classify_deliverable(child.intent)
        if task_kind is DeliverableKind.ROLE_DEFAULT:
            return None
        current = self._ledger.employees.get(child.assignee)
        if current is None:  # an unknown assignee is the _unknown_assignees gate's job, not ours
            return None
        report_ids = {employee.id for employee in reports}
        if current.id not in report_ids:
            # Don't launder a non-report / unauthorized original into a valid assignment.
            return None
        current_kind = native_kind_for_role(current.role, roles)
        if current_kind is DeliverableKind.ROLE_DEFAULT or current_kind is task_kind:
            return None
        matches = [
            employee
            for employee in reports
            if employee.id != child.assignee
            and native_kind_for_role(employee.role, roles) is task_kind
        ]
        if not matches:
            return None
        matches.sort(key=lambda employee: employee.id)
        return matches[0].id

    def _outcome_mismatches(self, children: Sequence[ChildPlan]) -> tuple[OutcomeMismatch, ...]:
        """Children whose declared outcome their assignee's role cannot produce (BUG-006)."""
        seen: dict[str, Employee] = {}
        for child in children:
            if child.assignee is None or child.assignee in seen:
                continue
            employee = self._ledger.employees.get(child.assignee)
            if employee is not None:
                seen[child.assignee] = employee
        return outcome_mismatches(children, employees=tuple(seen.values()))

    def _is_direct_report(self, employee_id: str, *, manager_id: str | None) -> bool:
        employee = self._ledger.employees.get(employee_id)
        return manager_id is not None and employee is not None and employee.reports_to == manager_id

    def _manager_report_ids(self, parent: Task) -> tuple[str, ...]:
        from chorus.heartbeat._invokability import invokability_block

        manager_id = parent.assignee_employee_id
        if manager_id is None or parent.team_id is None:
            return ()
        workforce = LedgerWorkforce(self._ledger.employees)
        member_ids = {
            member.employee_id
            for member in self._ledger.team_members.members_of(parent.team_id)
            if member.employee_id != manager_id
        }
        reports = [
            employee
            for employee in self._ledger.employees.list()
            if employee.id in member_ids and employee.reports_to == manager_id
        ]
        manager_reports: list[str] = []
        for employee in reports:
            profile = self._ledger.management_profiles.get(employee.id)
            if (
                profile is not None
                and profile.active
                and profile.can_lead
                and invokability_block(workforce, employee.id) is None
            ):
                manager_reports.append(employee.id)
        manager_reports.sort()
        return tuple(manager_reports)

    def _ensure_plan_revision(self, parent_id: str, revision: str) -> str:
        """Record (once per beat) the parent's accepted decomposition plan; return its revision id.

        Idempotent: keyed on ``revision`` (the run_id), so a re-fired tool finds the existing revision
        and skips creation. The artifact anchors the claim's lineage guard to the parent task.
        """
        plan_revision_id = derive_id("planrev", revision)
        if self._ledger.artifact_revisions.get(plan_revision_id) is not None:
            return plan_revision_id
        artifact_id = derive_id("plan", parent_id, revision)
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
    "CapabilityReroute",
    "CapabilityService",
    "ChildPlan",
    "DecomposeResult",
    "ManagerAreaViolation",
    "OutcomeMismatch",
    "RoutedChildWave",
    "SubmitTaskResult",
]
