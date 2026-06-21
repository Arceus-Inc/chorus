"""Extra feature exercises — the 5 wired-but-untested surfaces from post-dev-wiring.md.

Each test drives the **live** facade + kernel (real ``Chorus.build`` company over a real SQLite
ledger), but asserts on the deterministic kernel mechanics rather than driving a model beat — so it
exercises the live system without burning model calls (and without contending with a running org
build). Run:

    uv run python standup-app/feature_tests_extra.py messages
    uv run python standup-app/feature_tests_extra.py dependencies
    uv run python standup-app/feature_tests_extra.py recovery
    uv run python standup-app/feature_tests_extra.py block
    uv run python standup-app/feature_tests_extra.py plangate
    uv run python standup-app/feature_tests_extra.py all
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feature_tests as ft
import run as app

from chorus import ApprovalDecision, Chorus
from chorus.ledger._models import (
    Message,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    WakeReason,
)
from chorus.recovery import reconcile

_ok = ft._ok


# ── 1. messages — send_message → wake → inbox ─────────────────────────────────────────────────────
async def test_messages(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● MESSAGES — send_message enqueues a MESSAGE wake + lands in the recipient's inbox\033[0m")
    alice = org.hire(name="alice", role="engineer")
    bob = org.hire(name="bob", role="engineer")

    wake = org.send_message(
        Message(id="msg_demo", to_employee_id=bob.id, from_employee_id=alice.id,
                body="handoff: the shared build key is BK-42")
    )
    ok1 = _ok("send_message returns a wake aimed at the recipient with reason MESSAGE",
              wake.reason is WakeReason.MESSAGE and wake.employee_id == bob.id,
              f"reason={wake.reason.value} to={wake.employee_id}")
    inbox = org._ledger.messages.inbox(bob.id)
    ok2 = _ok("the message is durably in the recipient's inbox",
              any(m.id == "msg_demo" and "BK-42" in m.body for m in inbox),
              f"inbox={[m.id for m in inbox]}")
    queued = org._ledger.wakes.queued(employee_id=bob.id)
    ok3 = _ok("a MESSAGE wake is queued — the recipient reads it on its next beat",
              any(w.reason is WakeReason.MESSAGE for w in queued),
              f"queued={[w.reason.value for w in queued]}")
    ok4 = _ok("the message did NOT wake the sender (mailbox is directional)",
              not any(w.reason is WakeReason.MESSAGE for w in org._ledger.wakes.queued(employee_id=alice.id)))
    return all((ok1, ok2, ok3, ok4))


# ── 2. dependencies — depends_on holds task 2 until task 1 is done ─────────────────────────────────
async def test_dependencies(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● DEPENDENCIES — a depends_on edge gates task 2 until task 1 is done\033[0m")
    eng = org.hire(name="dep-eng", role="engineer")
    t1 = org.submit("first: write a.txt", assignee=eng.id)
    t2 = org.submit("second: write b.txt (needs a.txt)", assignee=eng.id, depends_on=[t1.id])

    blockers = org._ledger.dependencies.unresolved_blockers(t2.id)
    ok1 = _ok("while task 1 is open, task 2 is gated by it (unresolved blocker)",
              blockers == [t1.id], f"unresolved_blockers(t2)={blockers}")
    ok2 = _ok("the gated task 2 shows task 1 in its inspector blockers",
              t1.id in [b for b in org.inspect.task(t2.id).blockers], "view.blockers")
    # No run was ever dispatched for the gated task.
    ran_before = list(org._ledger.runs.for_task(t2.id))
    ok3 = _ok("the gated task 2 never dispatched a beat while blocked", ran_before == [],
              f"runs(t2)={len(ran_before)}")

    org._ledger.tasks.set_status(t1.id, TaskStatus.DONE)  # task 1 completes
    after = org._ledger.dependencies.unresolved_blockers(t2.id)
    ok4 = _ok("once task 1 is DONE, task 2's gate clears (no unresolved blockers)",
              after == [], f"unresolved_blockers(t2)={after}")
    return all((ok1, ok2, ok3, ok4))


# ── 3. recovery — a stranded run is reaped and a recovery path opens ───────────────────────────────
async def test_recovery(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● RECOVERY — a crashed beat (expired lease) is reaped + the task recovers\033[0m")
    eng = org.hire(name="rec-eng", role="engineer")
    t = org.submit("do a thing that will 'crash' mid-beat", assignee=eng.id)
    run = org._ledger.runs.create(
        Run(id="run_stranded", employee_id=eng.id, task_id=t.id, status=RunStatus.RUNNING,
            lease_expires_at=datetime.now(UTC) - timedelta(minutes=5))  # lease already lapsed
    )
    org._ledger.tasks.checkout(t.id, employee_id=eng.id, run_id=run.id)  # task now in_progress, holding the run
    org._ledger.wakes.drop_queued(employee_id=eng.id)  # a crashed beat already consumed its wake → genuinely stranded

    report = reconcile(org._ledger, now=datetime.now(UTC))
    ok1 = _ok("the reconcile sweep reaps the orphaned run (expired lease)",
              run.id in report.reaped_runs, f"reaped={report.reaped_runs}")
    reaped = org._ledger.runs.get(run.id)
    ok2 = _ok("the reaped run is marked terminal (TIMED_OUT), its lock released",
              reaped is not None and reaped.status is RunStatus.TIMED_OUT,
              f"run.status={getattr(reaped, 'status', None)}")
    ok3 = _ok("the stranded task gets a recovery path (a card opened or re-dispatched)",
              bool(report.opened or report.recovered),
              f"opened={report.opened} recovered={report.recovered}")
    return all((ok1, ok2, ok3))


# ── 4. block escalation — a rejected child wakes its manager to react ──────────────────────────────
async def test_block(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● BLOCK ESCALATION — a rejected child terminalizes + wakes the manager to react\033[0m")
    moe = org.hire(name="moe-mgr", role="manager")
    eng = org.hire(name="blk-eng", role="engineer", reports_to=moe.id)
    # A manager-owned parent with one delegated child (mirrors decompose → delegate).
    org._ledger.tasks.submit(Task(id="task_parent", intent="parent goal",
                                  assignee_employee_id=moe.id, status=TaskStatus.IN_PROGRESS))
    org._ledger.tasks.submit(Task(id="task_child", intent="child deliverable", parent_id="task_parent",
                                  assignee_employee_id=eng.id, status=TaskStatus.IN_PROGRESS))

    author = org._ledger.employees.get(eng.id)
    assert author is not None
    org._scheduler._route_block("task_child", author=author)  # the reviewer 'block' routing

    child = org._ledger.tasks.get("task_child")
    ok1 = _ok("the blocked child is terminalized to REJECTED",
              child is not None and child.status is TaskStatus.REJECTED,
              f"child.status={getattr(child, 'status', None)}")
    waked = org._ledger.wakes.queued(employee_id=moe.id)
    ok2 = _ok("with the subtree wholly terminal, the manager is woken (CHILDREN_DONE) to react",
              any(w.reason is WakeReason.CHILDREN_DONE for w in waked),
              f"manager wakes={[w.reason.value for w in waked]}")
    return all((ok1, ok2))


# ── 5. plan gate — open_plan_gate holds a decompose until resolved ─────────────────────────────────
async def test_plangate(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● PLAN GATE — open_plan_gate withholds a manager's plan until a human approves\033[0m")
    moe = org.hire(name="plan-mgr", role="manager")
    org._ledger.tasks.submit(Task(id="task_goal", intent="a goal to decompose",
                                  assignee_employee_id=moe.id, status=TaskStatus.IN_PROGRESS))

    gate = org.governance.open_plan_gate("task_goal", reason="review the proposed decomposition")
    ok1 = _ok("open_plan_gate opens a pending PLAN_APPROVAL gate on the parent",
              gate is not None and gate.action.value == "plan_approval",
              f"action={getattr(gate.action, 'value', None)}")
    inbox = org.governance.approvals()
    ok2 = _ok("the plan gate shows in the open-approval inbox (the decompose is held)",
              any(a.id == gate.id for a in inbox), f"inbox={[a.id for a in inbox]}")

    org.governance.resolve(gate.id, decision=ApprovalDecision.APPROVE, by="ceo")
    still_open = any(a.id == gate.id for a in org.governance.approvals())
    ok3 = _ok("after APPROVE the gate clears (the manager may now proceed)", not still_open,
              f"still_open={still_open}")
    return all((ok1, ok2, ok3))


_TESTS = {
    "messages": test_messages,
    "dependencies": test_dependencies,
    "recovery": test_recovery,
    "block": test_block,
    "plangate": test_plangate,
}


async def _amain(which: list[str]) -> int:
    os.environ.setdefault("CHORUS_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env"))
    for v in app._REQUIRED:
        os.environ.pop(v, None)
    app._load_env()
    if not all(os.environ.get(v) for v in app._REQUIRED):
        print("No model creds (need " + ", ".join(app._REQUIRED) + ")")
        return 2

    results: dict[str, bool] = {}
    for name in which:
        base = Path(tempfile.mkdtemp(prefix=f"chorus-xfeat-{name}-"))
        org, _factory, company_main = app._build_company(base, c=app._C(on=False), timeout_s=60.0)
        try:
            results[name] = await _TESTS[name](org, company_main, base)
        except Exception as exc:  # a probe that errors is a FAIL, not a crash
            import traceback
            traceback.print_exc()
            results[name] = _ok(f"{name} raised", False, str(exc))

    print("\n\033[97;1m── summary ──\033[0m")
    for name, passed in results.items():
        print(f"  {name:12s}: {'PASS' if passed else 'FAIL'}")
    return 0 if all(results.values()) else 1


def main() -> int:
    args = sys.argv[1:] or ["all"]
    which = list(_TESTS) if args == ["all"] else [a for a in args if a in _TESTS]
    if not which:
        print(f"usage: feature_tests_extra.py [{'|'.join(_TESTS)}|all]")
        return 2
    return asyncio.run(_amain(which))


if __name__ == "__main__":
    raise SystemExit(main())
