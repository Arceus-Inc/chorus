"""The governance resolver — a thin, atomic, audited dispatcher (spec 04 §5, Approach A).

An ``approval`` is the governed-action queue: opening one parks/flags its subject, resolving it
*performs the org mutation*. This resolver owns neither the open- nor the resolve-side effect — it
opens a transaction, stamps the approval, audits it, and delegates the mutation to the
:class:`GovernedAction` handler registered for the approval's :class:`ApprovalAction`. Adding an
action is one handler in :func:`~chorus.governance.default_actions`, never an edit here.

``open_task_gate`` stays as the task-gate convenience used by the ``human_approval`` DoD hook + CLI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from chorus.governance._errors import GovernanceError
from chorus.governance._registry import GovernanceRegistry, default_actions
from chorus.governance._types import ActionOutcome, ApprovalDecision, HumanAuthorization
from chorus.ids import mint_id
from chorus.ledger import (
    Activity,
    ActivityVerb,
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    AuthorizationVerdict,
    HumanAuthorizationProof,
    TaskStatus,
)
from chorus.outcomes import DoDKind

if TYPE_CHECKING:
    from chorus.heartbeat._landed_outcome import DerivedLandedOutcome
    from chorus.ledger import Ledger
    from chorus.observability import EventSink

_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})
_logger = logging.getLogger("chorus.governance.resolver")

_DECISION_VERB: dict[ApprovalDecision, ActivityVerb] = {
    ApprovalDecision.APPROVE: ActivityVerb.APPROVED,
    ApprovalDecision.DENY: ActivityVerb.DENIED,
    ApprovalDecision.REQUEST_REVISION: ActivityVerb.REVISION_REQUESTED,
}

_DECISION_VERDICT: dict[ApprovalDecision, AuthorizationVerdict] = {
    ApprovalDecision.APPROVE: AuthorizationVerdict.APPROVE,
    ApprovalDecision.DENY: AuthorizationVerdict.DENY,
    ApprovalDecision.REQUEST_REVISION: AuthorizationVerdict.REQUEST_REVISION,
}


@dataclass(frozen=True)
class ResolveOutcome:
    """What resolving an approval did — the decision and the gated subject's new status (spec 04 §5)."""

    approval_id: str
    subject_id: str
    decision: ApprovalStatus
    subject_status: str
    wakes_fired: int
    landed: DerivedLandedOutcome | None = None


class GovernanceResolver:
    """Open and resolve governed-action approvals over a ledger, dispatching to handlers (spec 04 §5)."""

    def __init__(
        self,
        ledger: Ledger,
        registry: GovernanceRegistry | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self._ledger = ledger
        self._registry = registry or GovernanceRegistry.from_actions(default_actions(ledger))
        self._event_sink = event_sink

    # -- opening ----------------------------------------------------------------------------------

    def open(
        self,
        *,
        action: ApprovalAction,
        subject_kind: ApprovalSubjectKind,
        subject_id: str,
        reason: str,
        gate_kind: ApprovalGate | None = None,
    ) -> Approval:
        """Open a pending gate and let its handler park/flag the subject — atomic + audited.

        The exact-once index rejects a second open gate on the same subject (a duplicate raises)."""
        handler = self._registry.get(action)
        approval = Approval(
            id=mint_id(),
            subject_kind=subject_kind,
            subject_id=subject_id,
            reason=reason,
            action=action,
            gate_kind=gate_kind,
        )
        with self._ledger.transaction():
            opened = self._ledger.approvals.request(approval)
            handler.on_open(opened)
            self._audit(ActivityVerb.GATED, opened, actor=None)
        return opened

    def open_plan_gate(self, parent_id: str, *, reason: str) -> Approval:
        """Hold a freshly-decomposed parent's children ``blocked`` and open its plan-approval gate.

        Called right after a manager decomposes when ``policy.plan_gate_required`` — the children were
        created ``todo`` + assignment-waked, so each is demoted to ``blocked`` and its queued wake
        dropped, parking the plan until a human signs it off (approve releases them again)."""
        for child in self._ledger.tasks.children(parent_id):
            if child.status is TaskStatus.TODO:
                self._ledger.tasks.set_status(child.id, TaskStatus.BLOCKED)
                if child.assignee_employee_id is not None:
                    self._ledger.wakes.drop_queued(employee_id=child.assignee_employee_id)
        return self.open(
            action=ApprovalAction.PLAN_APPROVAL,
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=parent_id,
            reason=reason,
        )

    def open_task_gate(self, task_id: str, *, gate_kind: ApprovalGate, reason: str) -> Approval:
        """Open a task acceptance/authorization gate (the ``human_approval`` DoD hook + CLI path)."""
        task = self._ledger.tasks.get(task_id)
        if task is None:
            raise GovernanceError(f"no such task: {task_id!r}")
        if task.status in _TERMINAL:
            raise GovernanceError(f"task {task_id!r} is {task.status.value} (terminal)")
        # One active gate per task. A duplicate is a domain error the caller should hear cleanly,
        # not a leaked sqlite UNIQUE(subject_kind, subject_id) IntegrityError (which also masks any
        # *other* integrity fault). A genuine race that slips past this still raises — a real fault.
        pending = next(
            (
                a
                for a in self._ledger.approvals.for_subject(task_id)
                if a.status is ApprovalStatus.PENDING
            ),
            None,
        )
        if pending is not None:
            raise GovernanceError(f"task {task_id!r} already has a pending gate ({pending.id})")
        return self.open(
            action=ApprovalAction.TASK_GATE,
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=task_id,
            reason=reason,
            gate_kind=gate_kind,
        )

    # -- resolving --------------------------------------------------------------------------------

    def resolve(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
        decided_by_user_id: str,
        now: datetime,
    ) -> ResolveOutcome:
        """Resolve a pending gate; its handler performs the org mutation — atomic + audited.

        Raises :class:`GovernanceError` for an unknown approval or one that is no longer pending."""
        del now  # stamping is the repo's job; kept for a stable governance-call signature
        return self._resolve(
            approval_id,
            decision=decision,
            decided_by_user_id=decided_by_user_id,
            proof=None,
        )

    def resolve_authenticated(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
        authorization: HumanAuthorization,
    ) -> ResolveOutcome:
        """Resolve a gate with durable proof of one authenticated, terminal human decision.

        ``ApprovalDecision`` deliberately has no ``HOLD`` member. Use
        :meth:`hold_authenticated` to evidence a hold while leaving the approval pending.
        """
        proof = HumanAuthorizationProof(
            decision_id=authorization.decision_id,
            approval_id=approval_id,
            user_id=authorization.user_id,
            method=authorization.method,
            authenticated_at=authorization.authenticated_at,
            nonce=authorization.nonce,
            decided_at=authorization.decided_at,
            request_id=authorization.request_id,
            request_hash=authorization.request_hash,
            verdict=_DECISION_VERDICT[decision],
        )
        return self._resolve(
            approval_id,
            decision=decision,
            decided_by_user_id=authorization.user_id,
            proof=proof,
        )

    def hold_authenticated(
        self, approval_id: str, *, authorization: HumanAuthorization
    ) -> HumanAuthorizationProof:
        """Record an authenticated hold without resolving the approval or invoking its handler."""
        approval = self._ledger.approvals.get(approval_id)
        if approval is None:
            raise GovernanceError(f"no such approval: {approval_id!r}")
        if approval.status is not ApprovalStatus.PENDING:
            raise GovernanceError(f"approval {approval_id!r} already {approval.status.value}")
        proof = HumanAuthorizationProof(
            decision_id=authorization.decision_id,
            approval_id=approval_id,
            user_id=authorization.user_id,
            method=authorization.method,
            authenticated_at=authorization.authenticated_at,
            nonce=authorization.nonce,
            decided_at=authorization.decided_at,
            request_id=authorization.request_id,
            request_hash=authorization.request_hash,
            verdict=AuthorizationVerdict.HOLD,
        )
        with self._ledger.transaction():
            self._ledger.human_authorization_proofs.record(proof)
            self._audit(ActivityVerb.HELD, approval, actor=authorization.user_id)
        return proof

    def get_authorization_proof(self, approval_id: str) -> HumanAuthorizationProof | None:
        """Read an approval's immutable human authorization proof, if it has one."""
        return self._ledger.human_authorization_proofs.get(approval_id)

    def get_authorization_proofs(self, approval_id: str) -> list[HumanAuthorizationProof]:
        """Read every immutable hold and terminal proof recorded for an approval."""
        return self._ledger.human_authorization_proofs.for_approval(approval_id)

    def get_authorization_proof_by_nonce(self, nonce: str) -> HumanAuthorizationProof | None:
        """Read immutable evidence for a derived Idempotency-Key nonce in this tenant.

        Podium compares this proof's canonical ``request_hash`` with the incoming body: equal hashes
        are a replay; a different hash is Idempotency-Key reuse and must be refused. ``request_id``
        remains the independent X-Request-ID audit correlation value.
        """
        return self._ledger.human_authorization_proofs.get_by_nonce(nonce)

    def get_landed_outcome(self, approval_id: str) -> DerivedLandedOutcome | None:
        """Replay the exact-once landed receipt durably committed with an approval decision."""
        from chorus.heartbeat._landed_outcome import DerivedLandedOutcome

        activity = next(
            (
                row
                for row in self._ledger.activity.by_subject("approval", approval_id)
                if row.verb is ActivityVerb.OUTCOME_LANDED
            ),
            None,
        )
        return None if activity is None else DerivedLandedOutcome.from_dict(activity.payload)

    def _resolve(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
        decided_by_user_id: str,
        proof: HumanAuthorizationProof | None,
    ) -> ResolveOutcome:
        approval = self._ledger.approvals.get(approval_id)
        if approval is None:
            raise GovernanceError(f"no such approval: {approval_id!r}")
        if approval.status is not ApprovalStatus.PENDING:
            raise GovernanceError(f"approval {approval_id!r} already {approval.status.value}")
        if (
            proof is None
            and approval.action is ApprovalAction.TASK_GATE
            and approval.gate_kind in {ApprovalGate.ACCEPTANCE, ApprovalGate.AUTHORIZATION}
        ):
            raise GovernanceError(
                f"task-gate approval {approval_id!r} requires authenticated resolution"
            )
        handler = self._registry.get(approval.action)
        apply: dict[ApprovalDecision, Callable[[Approval], ActionOutcome]] = {
            ApprovalDecision.APPROVE: handler.on_approve,
            ApprovalDecision.DENY: handler.on_deny,
            ApprovalDecision.REQUEST_REVISION: handler.on_revise,
        }
        landed: DerivedLandedOutcome | None = None
        with self._ledger.transaction():
            decided_at = proof.decided_at if proof is not None else None
            resolved = self._ledger.approvals.set_status(
                approval_id,
                decision.status,
                decided_by_user_id=decided_by_user_id,
                decided_at=decided_at,
            )
            if not resolved:
                raise GovernanceError(f"approval {approval_id!r} is no longer pending")
            if proof is not None:
                self._ledger.human_authorization_proofs.record(proof)
            outcome = apply[decision](approval)
            self._audit(_DECISION_VERB[decision], approval, actor=decided_by_user_id)
            if proof is not None:
                landed = self._persist_human_acceptance_landed(approval, decision, proof)
        if proof is not None and landed is not None:
            try:
                self._emit_human_acceptance_landed(approval, proof, landed)
            except Exception:
                _logger.warning(
                    "live outcome delivery failed for committed approval %s; durable receipt remains",
                    approval.id,
                    exc_info=True,
                )
        return ResolveOutcome(
            approval_id=approval_id,
            subject_id=approval.subject_id,
            decision=decision.status,
            subject_status=outcome.subject_status,
            wakes_fired=outcome.wakes_fired,
            landed=landed,
        )

    def _persist_human_acceptance_landed(
        self,
        approval: Approval,
        decision: ApprovalDecision,
        proof: HumanAuthorizationProof,
    ) -> DerivedLandedOutcome | None:
        """Commit the sole landed receipt atomically with a HumanApproval decision."""
        if (
            approval.action is not ApprovalAction.TASK_GATE
            or approval.gate_kind is not ApprovalGate.ACCEPTANCE
        ):
            return None
        verifier = self._ledger.dod.verifier_for_task(approval.subject_id)
        if verifier is None or verifier.kind is not DoDKind.HUMAN_APPROVAL:
            return None
        task = self._ledger.tasks.get(approval.subject_id)
        if task is None:
            return None

        from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
        from chorus.heartbeat._landed_outcome import derive_landed_outcome

        passed = decision is ApprovalDecision.APPROVE
        dod = self._ledger.dod.get_for_task(task.id)
        if dod is None:
            return None
        landed = derive_landed_outcome(
            task,
            BeatOutcome(
                passed=passed,
                summary=f"human acceptance {decision.value}",
                disposition=(BeatDisposition.PASSED if passed else BeatDisposition.DOD_FAILED),
            ),
            dod.status,
            orchestrated=False,
            integration=dod.integration_verdict,
        )
        self._ledger.activity.append(
            Activity(
                id=mint_id(),
                verb=ActivityVerb.OUTCOME_LANDED,
                subject_kind="approval",
                subject_id=approval.id,
                actor_user_id=proof.user_id,
                payload={
                    **landed.to_dict(),
                    "approval_id": approval.id,
                    "decision_id": proof.decision_id,
                    "task_id": task.id,
                    "employee_id": task.assignee_employee_id,
                    "run_id": self._accepted_run_id(task.id),
                    "decided_at": proof.decided_at.isoformat(),
                    "passed": landed.strategy_passed(),
                    "recovery_hint": landed.recovery_hint().value,
                },
            )
        )
        return landed

    def _emit_human_acceptance_landed(
        self,
        approval: Approval,
        proof: HumanAuthorizationProof,
        landed: DerivedLandedOutcome,
    ) -> None:
        """Project a committed landed receipt live; durable truth never depends on this sink."""
        task = self._ledger.tasks.get(approval.subject_id)
        if task is None:
            return

        from chorus.heartbeat._landed_event import emit_derived_landed_outcome

        emit_derived_landed_outcome(
            self._ledger,
            self._event_sink,
            task=task,
            landed=landed,
            at=proof.decided_at,
            employee_id=task.assignee_employee_id,
            run_id=self._accepted_run_id(task.id),
        )

    def _accepted_run_id(self, task_id: str) -> str | None:
        contract = self._ledger.delegation_contracts.get(task_id)
        return contract.accepted_run_id if contract is not None else None

    # -- audit ------------------------------------------------------------------------------------

    def _audit(self, verb: ActivityVerb, approval: Approval, *, actor: str | None) -> None:
        self._ledger.activity.append(
            Activity(
                id=mint_id(),
                verb=verb,
                subject_kind=approval.subject_kind.value,
                subject_id=approval.subject_id,
                actor_user_id=actor,
            )
        )


__all__ = ["GovernanceError", "GovernanceResolver", "ResolveOutcome"]
