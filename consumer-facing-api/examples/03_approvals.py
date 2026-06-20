"""03 — approvals (governance gates).  OFFLINE: no model, no creds.

Some work needs a human's sign-off. Open a gate on a task, see it in the open inbox, resolve it. A
resolution runs the gate's effect atomically — an ``AUTHORIZATION`` approve releases the task to ``todo``;
a deny leaves it gated. This is how a person (or, later, horizon) unblocks work the org parked.

    uv run python consumer-facing-api/examples/03_approvals.py
"""

from __future__ import annotations

from _common import offline_org

from chorus import ApprovalDecision, ApprovalGate


def main() -> None:
    org = offline_org().chorus
    org.hire(name="moe", role="manager")
    task = org.submit("ship the pricing change", assignee="moe")
    print(f"submitted {task.id}: {org.inspect.task(task.id).status.value}")

    appr = org.governance.open_gate(task.id, gate_kind=ApprovalGate.AUTHORIZATION, reason="needs sign-off")
    print(f"opened gate {appr.id} → task is now {org.inspect.task(task.id).status.value}")
    print(f"open inbox: {[a.id for a in org.governance.approvals()]}")

    org.governance.resolve(appr.id, decision=ApprovalDecision.APPROVE, by="ceo")
    print(f"approved by ceo → task is now {org.inspect.task(task.id).status.value}")
    print(f"open inbox: {[a.id for a in org.governance.approvals()]}")


if __name__ == "__main__":
    main()
