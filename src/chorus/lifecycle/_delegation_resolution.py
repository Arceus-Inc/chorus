"""Public lifecycle policy for resolving a verified delegation parent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.ledger._models import ActivityVerb, DelegationContractStatus
from chorus.lifecycle._audit import record_activity
from chorus.lifecycle._team_policy import MissionTeamPolicy

if TYPE_CHECKING:
    from chorus.ledger import DelegationContract, Ledger


class DelegationResolutionError(RuntimeError):
    """The durable contract is not in a state that can accept this resolution."""


class DelegationResolutionPolicy:
    """Close or return a verifying delegation after its terminal acceptance decision."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def ensure_approvable(self, task_id: str) -> None:
        """Raise if a live contract exists that cannot close from its current status."""
        contract = self._ledger.delegation_contracts.get(task_id)
        if contract is None or contract.status is DelegationContractStatus.DONE:
            return
        if contract.status is not DelegationContractStatus.VERIFYING:
            raise DelegationResolutionError(
                f"delegation task {task_id!r} cannot close from {contract.status.value!r}"
            )
        if contract.accepted_run_id is None:
            raise DelegationResolutionError(f"delegation task {task_id!r} has no accepted run")

    def approve(self, task_id: str, *, recovered: bool = False) -> bool:
        contract = self._ledger.delegation_contracts.get(task_id)
        if contract is None or contract.status is DelegationContractStatus.DONE:
            return False
        self.ensure_approvable(task_id)
        run_id = self._accepted_run_id(contract)
        with self._ledger.transaction():
            self._record(contract, passed=True, decision=None, recovered=recovered)
            self._ledger.delegation_contracts.update_status(task_id, DelegationContractStatus.DONE)
            MissionTeamPolicy(self._ledger).archive(contract.team_id)
            if recovered:
                self._ledger.tasks.release_locks(task_id, run_id=run_id)
                run = self._ledger.runs.get(run_id)
                if run is not None and run.wake_id is not None:
                    self._ledger.wakes.mark_done(run.wake_id)
        return True

    def deny(self, task_id: str) -> bool:
        return self._return(task_id, DelegationContractStatus.BLOCKED, decision="deny")

    def request_revision(self, task_id: str) -> bool:
        return self._return(
            task_id,
            DelegationContractStatus.INTEGRATING,
            decision="request_revision",
        )

    def _return(
        self,
        task_id: str,
        status: DelegationContractStatus,
        *,
        decision: str,
    ) -> bool:
        contract = self._verifying(task_id)
        if contract is None:
            return False
        with self._ledger.transaction():
            self._record(contract, passed=False, decision=decision, recovered=False)
            self._ledger.delegation_contracts.update_status(task_id, status)
        return True

    def _verifying(self, task_id: str) -> DelegationContract | None:
        contract = self._ledger.delegation_contracts.get(task_id)
        if contract is None or contract.status is not DelegationContractStatus.VERIFYING:
            return None
        return contract

    @staticmethod
    def _accepted_run_id(contract: DelegationContract) -> str:
        if contract.accepted_run_id is None:
            raise DelegationResolutionError(
                f"delegation task {contract.task_id!r} has no accepted run"
            )
        return contract.accepted_run_id

    def _record(
        self,
        contract: DelegationContract,
        *,
        passed: bool,
        decision: str | None,
        recovered: bool,
    ) -> None:
        record_activity(
            self._ledger,
            verb=ActivityVerb.PARENT_VERIFIED,
            subject_kind="delegation_contract",
            subject_id=contract.task_id,
            payload={
                "passed": passed,
                "run_id": self._accepted_run_id(contract),
                **({"decision": decision} if decision is not None else {}),
                **({"recovered": True} if recovered else {}),
            },
        )


__all__ = ["DelegationResolutionError", "DelegationResolutionPolicy"]
