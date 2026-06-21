"""LIVE end-to-end exercises — each drives REAL model beats (not deterministic kernel pokes).

Every test stands up a live ``Chorus.build`` company and dispatches actual gpt-5.2 beats through the
heartbeat, so the feature is exercised exactly as production would. Each prints the live flow and a
PASS/FAIL on a *behavioural* signal (a file the model had to produce, an ordering it had to respect).

    uv run python standup-app/feature_tests_live.py messages
    uv run python standup-app/feature_tests_live.py dependencies
    uv run python standup-app/feature_tests_live.py recovery
    uv run python standup-app/feature_tests_live.py block
    uv run python standup-app/feature_tests_live.py plangate
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

from chorus import Chorus, TaskStatus, Verifier
from chorus.governance import GovernancePolicy
from chorus.groups import GovernanceFacade
from chorus.ledger._models import Message, Run, RunStatus

_ok = ft._ok
_drive = ft._drive
_gate = ft._file_present_gate
_branch_file = ft._branch_file


# ── 1. MESSAGES — the recipient READS the inbox message inside its beat ────────────────────────────
async def live_messages(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● MESSAGES (live) — an inbox message steers what the engineer's beat produces\033[0m")
    eng = org.hire(name="mia", role="engineer")
    # A task that defers entirely to the inbox — the only place the real instruction exists.
    task = org.submit(
        "Read the single instruction message in your inbox and carry it out EXACTLY. Do only what it "
        "says, touch no other files, do not run pip install or git push.",
        assignee=eng.id,
        dod=_gate("inbox_proof.txt", contains=("TOKEN-MSG-42",)),
    )
    org.send_message(Message(
        id="msg_live", to_employee_id=eng.id, from_user_id="ceo",
        body="Instruction: create a file named inbox_proof.txt whose only line is exactly TOKEN-MSG-42",
    ))
    print(f"    submitted {task.id} → mia, then sent the real instruction as a MESSAGE")
    final = await _drive(org, task.id, max_pulses=8)
    body = _branch_file(company_main, eng.id, "inbox_proof.txt") if final == "done" else ""
    return _ok("the engineer READ the inbox message in-beat and produced exactly what it asked",
               final == "done" and "TOKEN-MSG-42" in body, f"status={final} file={body[:50]!r}")


# ── 2. DEPENDENCIES — task 2 only runs after task 1 is DONE ────────────────────────────────────────
async def live_dependencies(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● DEPENDENCIES (live) — a depends_on edge holds task 2 until task 1 lands\033[0m")
    eng = org.hire(name="dan", role="engineer")
    t1 = org.submit("Create a.txt whose only line is STEP-ONE-DONE.", assignee=eng.id,
                    dod=_gate("a.txt", contains=("STEP-ONE-DONE",)))
    t2 = org.submit("Create b.txt whose only line is STEP-TWO-DONE.", assignee=eng.id,
                    depends_on=[t1.id], dod=_gate("b.txt", contains=("STEP-TWO-DONE",)))
    print(f"    t1={t1.id}  t2={t2.id} (t2 depends_on t1)")

    t2_ran_early = False
    for n in range(1, 14):
        await org.tick()
        await org.drain()
        s1 = org.inspect.task(t1.id).status
        s2 = org.inspect.task(t2.id).status
        t2_has_run = bool(list(org._ledger.runs.for_task(t2.id)))
        print(f"    pulse {n}: t1={s1.value}  t2={s2.value}  t2_dispatched={t2_has_run}")
        if t2_has_run and s1 is not TaskStatus.DONE:
            t2_ran_early = True  # t2 must NEVER dispatch a beat before t1 is done
        if s1 is TaskStatus.DONE and s2 is TaskStatus.DONE:
            break

    ok1 = _ok("task 2 never dispatched a beat while task 1 was unfinished (the gate held)", not t2_ran_early)
    ok2 = _ok("both eventually run to DONE — task 2 unblocked only after task 1 landed",
              org.inspect.task(t1.id).status is TaskStatus.DONE and org.inspect.task(t2.id).status is TaskStatus.DONE,
              f"t1={org.inspect.task(t1.id).status.value} t2={org.inspect.task(t2.id).status.value}")
    return ok1 and ok2


# ── 3. RECOVERY — a stranded run is reaped, then a REAL beat re-runs the task to done ───────────────
async def live_recovery(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● RECOVERY (live) — a 'crashed' beat is reaped, then re-dispatched + re-run for real\033[0m")
    eng = org.hire(name="rob", role="engineer")
    t = org.submit("Create rec.txt whose only line is RECOVERED-OK.", assignee=eng.id,
                   dod=_gate("rec.txt", contains=("RECOVERED-OK",)))
    # Simulate a worker that died mid-beat: a running run with a lapsed lease, holding the task; its
    # wake already consumed. The kernel must detect the orphan and re-drive the work for real.
    run = org._ledger.runs.create(Run(id="run_crash", employee_id=eng.id, task_id=t.id,
                                      status=RunStatus.RUNNING,
                                      lease_expires_at=datetime.now(UTC) - timedelta(minutes=5)))
    org._ledger.tasks.checkout(t.id, employee_id=eng.id, run_id=run.id)
    org._ledger.wakes.drop_queued(employee_id=eng.id)
    print(f"    injected a stranded RUNNING run {run.id} (lease lapsed) on {t.id} — now driving the heartbeat")

    final = await _drive(org, t.id, max_pulses=10)
    reaped = org._ledger.runs.get("run_crash")
    body = _branch_file(company_main, eng.id, "rec.txt") if final == "done" else ""
    ok1 = _ok("the orphaned run was reaped (TIMED_OUT)",
              reaped is not None and reaped.status is RunStatus.TIMED_OUT, f"run={getattr(reaped,'status',None)}")
    ok2 = _ok("after recovery a REAL beat re-ran the task to DONE and landed the file",
              final == "done" and "RECOVERED-OK" in body, f"status={final} file={body[:40]!r}")
    return ok1 and ok2


# ── 4. BLOCK ESCALATION — a failing DoD blocks, the author is re-dispatched, then it escalates ──────
async def live_block(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● BLOCK ESCALATION (live) — a build that can't pass its DoD blocks → re-dispatch → escalate\033[0m")
    eng = org.hire(name="ben", role="engineer")
    # The task asks for x.txt, but the DoD demands a DIFFERENT file the brief never mentions — so the
    # objective floor fails every build → reviewer 'block' → _route_block re-dispatches the author up to
    # max_review_rounds, then escalates to BLOCKED + a recovery card.
    # DoD = `false` — an objective floor no build can ever pass, so every review round blocks.
    t = org.submit("Create x.txt whose only line is HELLO.", assignee=eng.id,
                   dod=Verifier.command("false"))
    print(f"    submitted {t.id} with an unsatisfiable DoD — driving the review/escalation ladder")
    final = await _drive(org, t.id, max_pulses=12)
    runs = list(org._ledger.runs.for_task(t.id))
    card = org._ledger.recovery_actions.active_for_source(t.id)
    ok1 = _ok("the build is blocked and the author was re-dispatched (multiple review rounds)",
              len(runs) >= 2, f"runs={len(runs)}")
    ok2 = _ok("after the review rounds are exhausted it escalates (BLOCKED + a recovery card)",
              final == "blocked" and card is not None, f"status={final} recovery_card={getattr(card,'id',None)}")
    return ok1 and ok2


# ── 5. PLAN GATE — a manager's decompose is withheld until a human approves the plan ───────────────
async def live_plangate(org: Chorus, company_main: Path, base: Path) -> bool:
    print("\n\033[96m● PLAN GATE (live) — a manager decomposes, the plan is HELD pending approval, then proceeds\033[0m")
    # Arm the plan gate for managers over the same ledger/workforce/roles.
    org._governance = GovernanceFacade(
        org._ledger, org._workforce, org._roles,
        GovernancePolicy(plan_approval_roles=frozenset({"manager"})),
    )
    moe = org.hire(name="meg", role="manager")
    org.hire(name="eve", role="engineer", reports_to=moe.id)
    goal = org.submit(
        "Decompose this across your engineer: create two files, p1.txt (one line: AAA) and p2.txt "
        "(one line: BBB). Delegate each as a child task.",
        assignee=moe.id,
    )
    print(f"    submitted goal {goal.id} → meg (manager); driving until the decompose + plan gate appear")
    for n in range(1, 8):
        await org.tick()
        await org.drain()
        gates = org.governance.approvals()
        kids = org._ledger.tasks.children(goal.id)
        print(f"    pulse {n}: goal={org.inspect.task(goal.id).status.value}  open_gates={[g.id for g in gates]}  children={len(kids)}")
        if gates:
            break
    gates = org.governance.approvals()
    plan_gates = [g for g in gates if g.action.value == "plan_approval"]
    ok1 = _ok("the manager's decompose opened a PLAN_APPROVAL gate that holds the children",
              len(plan_gates) >= 1, f"plan_gates={[g.id for g in plan_gates]}")
    if not plan_gates:
        return False

    from chorus import ApprovalDecision
    org.governance.resolve(plan_gates[0].id, decision=ApprovalDecision.APPROVE, by="ceo")
    print(f"    approved the plan {plan_gates[0].id} — driving the now-released children")
    for _n in range(1, 12):
        await org.tick()
        await org.drain()
        if org.inspect.task(goal.id).status in (TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.REJECTED):
            break
    landed = ft.app._git(company_main, "ls-files")
    ok2 = _ok("after approval the released children run and at least one delegated file lands",
              ("p1.txt" in landed or "p2.txt" in landed), f"tracked includes p1/p2? {('p1.txt' in landed, 'p2.txt' in landed)}")
    return ok1 and ok2


_TESTS = {
    "messages": live_messages,
    "dependencies": live_dependencies,
    "recovery": live_recovery,
    "block": live_block,
    "plangate": live_plangate,
}


async def _amain(which: list[str]) -> int:
    os.environ.setdefault("CHORUS_ENV_FILE", str(Path(__file__).resolve().parent.parent / ".env"))
    for v in app._REQUIRED:
        os.environ.pop(v, None)
    app._load_env()
    if not all(os.environ.get(v) for v in app._REQUIRED):
        print("No model creds")
        return 2
    results: dict[str, bool] = {}
    for name in which:
        base = Path(tempfile.mkdtemp(prefix=f"chorus-live-{name}-"))
        org, _f, company_main = app._build_company(base, c=app._C(on=False), timeout_s=180.0)
        try:
            results[name] = await _TESTS[name](org, company_main, base)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            results[name] = _ok(f"{name} raised", False, str(exc))
        print(f"    (workspace: {base})")
    print("\n\033[97;1m── live summary ──\033[0m")
    for name, passed in results.items():
        print(f"  {name:12s}: {'PASS' if passed else 'FAIL'}")
    return 0 if all(results.values()) else 1


def main() -> int:
    args = sys.argv[1:] or ["messages"]
    which = list(_TESTS) if args == ["all"] else [a for a in args if a in _TESTS]
    if not which:
        print(f"usage: feature_tests_live.py [{'|'.join(_TESTS)}|all]")
        return 2
    return asyncio.run(_amain(which))


if __name__ == "__main__":
    raise SystemExit(main())
